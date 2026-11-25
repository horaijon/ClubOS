"""Durable workflow telemetry in a sidecar journal.

The journal can publish progress while the business transaction holds SQLite's
writer lock. Only a successful business commit emits state_updated.
"""
import asyncio
import json
import sqlite3
from contextlib import closing, contextmanager
from time import monotonic, perf_counter

from fastapi import Request
from fastapi.responses import StreamingResponse

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs(
  run_id TEXT PRIMARY KEY, parent_run_id TEXT, club_id TEXT NOT NULL, event_id TEXT,
  trace_id TEXT NOT NULL, request_id TEXT, agent_name TEXT NOT NULL,
  status TEXT NOT NULL, timestamp TEXT NOT NULL, latency_ms INTEGER
);
CREATE TABLE IF NOT EXISTS agent_step_logs(
  sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
  kind TEXT NOT NULL, tool_name TEXT, input_payload TEXT NOT NULL,
  output_payload TEXT NOT NULL, reasoning_summary TEXT NOT NULL,
  status TEXT NOT NULL, latency_ms INTEGER, timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS trace_event ON agent_runs(club_id,event_id,trace_id);
CREATE INDEX IF NOT EXISTS trace_steps ON agent_step_logs(run_id,sequence);
"""


def connect():
    path = db.database_path()
    connection = sqlite3.connect(path.with_name(path.name + ".trace.sqlite3"), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize():
    with closing(connect()) as connection, connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)
        interrupted = connection.execute("SELECT run_id,parent_run_id FROM agent_runs WHERE status='Running'").fetchall()
        for row in interrupted:
            connection.execute("UPDATE agent_runs SET status='Failed' WHERE run_id=?", (row["run_id"],))
            if row["parent_run_id"] is None:
                connection.execute("""INSERT INTO agent_step_logs
                    (run_id,kind,input_payload,output_payload,reasoning_summary,status,timestamp)
                    VALUES(?,'run_failed','{}','{}','Server restarted during execution. Check the workspace before retrying.','Failed',?)""",
                    (row["run_id"], db.now()))


def import_seed_history():
    with db.transaction() as state:
        history=db.rows(state,"""SELECT r.*,e.club_id FROM runs r JOIN events e ON e.id=r.event_id
            JOIN workflows w ON w.id=r.workflow_id WHERE e.is_demo=1 AND w.input_hash='seed'
            ORDER BY r.created_at,r.rowid""")
    with closing(connect()) as connection, connection:
        for run in history:
            root='demo-'+run['workflow_id']
            child='demo-'+run['id']
            if connection.execute('SELECT 1 FROM agent_runs WHERE run_id=?',(child,)).fetchone():
                continue
            ts=run['created_at']
            cols='run_id,parent_run_id,club_id,event_id,trace_id,agent_name,status,timestamp'
            created=connection.execute(f'INSERT OR IGNORE INTO agent_runs({cols}) VALUES(?,?,?,?,?,?,?,?)',
                (root,None,run['club_id'],run['event_id'],root,'Nexus','Completed',ts))
            if created.rowcount:
                connection.execute("""INSERT INTO agent_step_logs
                   (run_id,kind,input_payload,output_payload,reasoning_summary,status,timestamp)
                   VALUES(?,'agent_started',?,'{}','Imported demo workflow history.','Completed',?)""",
                   (root,db.encode({'trigger':run['trigger']+' · demo history'}),ts))
            connection.execute(f'INSERT INTO agent_runs({cols}) VALUES(?,?,?,?,?,?,?,?)',
                (child,root,run['club_id'],run['event_id'],root,run['agent'],run['status'],ts))
            connection.execute("""INSERT INTO agent_step_logs
                   (run_id,kind,tool_name,input_payload,output_payload,reasoning_summary,status,timestamp)
                   VALUES(?,'tool_finished',?,'{}',?,?,?,?)""",
                   (child,run['tool'],db.encode({'mode':run['mode'],'source':'demo seed'}),run['summary'],run['status'],ts))
        roots={run['workflow_id']:run for run in history}
        for wid,run in roots.items():
            root='demo-'+wid
            if connection.execute("SELECT 1 FROM agent_step_logs WHERE run_id=? AND kind='run_completed'",(root,)).fetchone():
                continue
            connection.execute("""INSERT INTO agent_step_logs
                   (run_id,kind,input_payload,output_payload,reasoning_summary,status,timestamp)
                   VALUES(?,'run_completed','{}','{}','Demo history loaded.','Completed',?)""",
                   (root,run['created_at']))


class Execution:
    def __init__(self, club_id, event_id, request_id, goal, job_id=None):
        self.club_id = club_id
        self.event_id = event_id
        self.request_id = request_id
        self.root_id = db.uid()
        self.trace_id = job_id or self.root_id
        self.goal = goal

    def emit(self, kind, summary, *, run_id=None, tool=None, inputs=None, outputs=None, status="Running", latency=None):
        with closing(connect()) as c, c:
            c.execute("""INSERT INTO agent_step_logs
                (run_id,kind,tool_name,input_payload,output_payload,reasoning_summary,status,latency_ms,timestamp)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (run_id or self.root_id,kind,tool,db.encode(inputs or {}),db.encode(outputs or {}),summary,status,latency,db.now()))

    def start(self, run_id, agent, parent=None):
        with closing(connect()) as c, c:
            c.execute("""INSERT INTO agent_runs(run_id,parent_run_id,club_id,event_id,trace_id,request_id,agent_name,status,timestamp)
                VALUES(?,?,?,?,?,?,?,'Running',?)""",
                (run_id,parent,self.club_id,self.event_id,self.trace_id,self.request_id,agent,db.now()))

    def finish(self, run_id, status, elapsed):
        with closing(connect()) as c,c:
            c.execute("UPDATE agent_runs SET status=?,latency_ms=? WHERE run_id=?",(status,elapsed,run_id))

    def attach_event(self,event_id):
        self.event_id = event_id
        with closing(connect()) as c,c:
            c.execute("UPDATE agent_runs SET event_id=? WHERE club_id=? AND trace_id=?",(event_id,self.club_id,self.trace_id))

    @contextmanager
    def step(self, agent, tool, inputs=None):
        run_id=db.uid()
        self.start(run_id,agent,self.root_id)
        if agent!="Nexus":
            self.emit("handoff",f"Nexus assigned {tool.replace('_',' ')} to {agent}.",run_id=run_id,tool=tool)
        self.emit("agent_started",f"{agent} started.",run_id=run_id,tool=tool)
        self.emit("tool_called",tool.replace("_"," "),run_id=run_id,tool=tool,inputs=inputs)
        mark=perf_counter()
        result={}
        status="Completed"
        try:
            yield result
        except Exception:
            status="Failed"
            result["summary"]="Tool failed. The workspace transaction was rolled back."
            raise
        finally:
            ms=round((perf_counter()-mark)*1000)
            self.finish(run_id,result.get("status",status),ms)
            self.emit("tool_finished", result.get("summary") or ("Tool completed." if status=="Completed" else "Tool failed."),
                      run_id=run_id,tool=tool,outputs=result.get("output"),status=result.get("status",status),latency=ms)

    @contextmanager
    def recording(self):
        self.start(self.root_id,"Nexus")
        self.emit("agent_started","Nexus received the workflow.",inputs={"trigger":self.goal})
        mark=perf_counter()
        try:
            yield self
        except Exception:
            self.finish(self.root_id,"Failed",round((perf_counter()-mark)*1000))
            self.emit("run_failed","Workflow stopped. Uncommitted changes were rolled back.",status="Failed")
            raise
        else:
            ms=round((perf_counter()-mark)*1000)
            self.emit("state_updated","Workspace transaction committed.",outputs={"event_id":self.event_id},status="Completed")
            self.finish(self.root_id,"Completed",ms)
            self.emit("run_completed","Workflow complete.",status="Completed",latency=ms)


def entries(club_id, column, value, cursor=None, limit=200):
    # The column is selected by a trusted route, never from request data.
    assert column in ("event_id","trace_id")
    with closing(connect()) as c:
        base=f"""SELECT s.*, r.parent_run_id,r.agent_name,r.trace_id,r.request_id,r.event_id FROM agent_step_logs s
                 JOIN agent_runs r USING(run_id) WHERE r.club_id=? AND r.{column}=?"""
        if cursor is None:
            found=c.execute(base+" ORDER BY s.sequence DESC LIMIT ?",(club_id,value,limit)).fetchall()[::-1]
        else:
            found=c.execute(base+" AND s.sequence>? ORDER BY s.sequence LIMIT ?",(club_id,value,cursor,limit)).fetchall()
    result=[]
    for row in found:
        item=dict(row)
        for field in ("input_payload","output_payload"):
            item[field]=json.loads(item[field])
        result.append(item)
    return result


def stream(request:Request,club_id,column,key):
    marker=request.headers.get("last-event-id","")
    cursor=int(marker) if marker.isdigit() and len(marker)<18 else None

    async def generate():
        nonlocal cursor
        heartbeat=monotonic()
        while not await request.is_disconnected():
            batch=await asyncio.to_thread(entries,club_id,column,key,cursor)
            for item in batch:
                cursor=item["sequence"]
                yield f"id: {cursor}\ndata: {db.encode(item)}\n\n"
                if column=="trace_id" and item["kind"] in ("run_completed","run_failed"):
                    return
            if monotonic()-heartbeat>=12:
                yield ": keep-alive\n\n"
                heartbeat=monotonic()
            await asyncio.sleep(.25)

    return StreamingResponse(generate(),media_type="text/event-stream",headers={"X-Accel-Buffering":"no","Cache-Control":"no-store"})
