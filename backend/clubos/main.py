"""Local demo entry point and bounded integration routes."""
import asyncio
from contextlib import asynccontextmanager, suppress
import hashlib
import logging
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
from . import api, db, engine
from .reports import event_report

logger = logging.getLogger(__name__)


def sweep():
    with db.transaction() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM events")]
    for event_id in ids:
        try:
            with db.transaction(write=True) as conn:
                engine.tick(conn,event_id)
        except Exception:
            logger.exception("Reminder sweep failed for an event")


async def reminders():
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(sweep)


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    with db.transaction(write=True) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS planning_jobs(
            job_id TEXT PRIMARY KEY,status TEXT NOT NULL,id TEXT,detail TEXT NOT NULL,input_hash TEXT NOT NULL)""")
        conn.execute("UPDATE planning_jobs SET status='failed', detail='Server restarted during planning. Check Events before retrying.' WHERE status IN ('running','queued')")
    worker = asyncio.create_task(reminders())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(title="ClubOS",version="1.0",lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost","127.0.0.1","testserver"])
app.include_router(api.router)


@app.middleware("http")
async def local_writes(request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET","HEAD","OPTIONS"} and origin:
        if origin not in {str(request.base_url).rstrip("/"),"http://127.0.0.1:5173","http://localhost:5173"}:
            return JSONResponse({"detail":"This demo accepts changes from its local workspace."},status_code=403)
    if request.headers.get("content-length","").isdigit() and int(request.headers["content-length"]) > 4_500_000:
        return JSONResponse({"detail":"Maximum request size is 4 MB."},status_code=413)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"status":"ready","gemini_configured":bool(os.getenv("GEMINI_API_KEY"))}


def run_planning(job_id, data):
    with db.transaction(write=True) as conn:
        conn.execute("UPDATE planning_jobs SET status='running',detail='Nexus is coordinating event planning.' WHERE job_id=?",(job_id,))
    try:
        result = api.create_event(data)
        event_id, status, detail = result["id"], "completed", "Event plan saved."
    except Exception as exc:
        event_id, status = None, "failed"
        detail = str(exc.detail)[:400] if isinstance(exc,HTTPException) else "Planning failed. Review the event inputs and try again."
        logger.warning("Planning failed (%s)",type(exc).__name__)
    with db.transaction(write=True) as conn:
        conn.execute("UPDATE planning_jobs SET status=?,id=?,detail=? WHERE job_id=?",(status,event_id,detail,job_id))


@app.post("/api/planning-jobs",status_code=202)
def start_planning(data: api.EventCreate, background: BackgroundTasks, idempotency_key: UUID | None=Header(None)):
    job_id = (idempotency_key or uuid4()).hex
    fingerprint = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    with db.transaction(write=True) as conn:
        existing = conn.execute("SELECT input_hash FROM planning_jobs WHERE job_id=?",(job_id,)).fetchone()
        if existing:
            if existing["input_hash"] != fingerprint:
                raise HTTPException(409,"This planning request was already used for a different event.")
            return {"job_id":job_id}
        conn.execute("INSERT INTO planning_jobs VALUES(?, 'queued', NULL, 'Waiting for Nexus.', ?)",(job_id,fingerprint))
    background.add_task(run_planning,job_id,data)
    return {"job_id":job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with db.transaction() as conn:
        row = conn.execute("SELECT job_id,status,id,detail FROM planning_jobs WHERE job_id=?",(job_id,)).fetchone()
    if row is None:
        raise HTTPException(404,"Planning job not found.")
    return dict(row)


def snapshot(event_id):
    with db.transaction() as conn:
        if not conn.execute("SELECT 1 FROM events WHERE id=?",(event_id,)).fetchone():
            raise HTTPException(404,"Event not found.")
        return engine.workspace(conn,event_id)


def pdf_response(content, filename):
    return Response(content,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{filename}.pdf"'})


@app.get("/api/events/{event_id}/report.pdf")
def event_pdf(event_id: str):
    return pdf_response(event_report(snapshot(event_id)), "ClubOS-event-report")


@app.get("/api/events/{event_id}/sponsors/{sponsor_id}/report.pdf")
def sponsor_pdf(event_id: str,sponsor_id: str):
    state = snapshot(event_id)
    sponsor = next((s for s in state["sponsors"] if s["id"]==sponsor_id),None)
    if not sponsor:
        raise HTTPException(404,"Sponsor not found in this event.")
    return pdf_response(event_report(state,sponsor),"ClubOS-sponsor-report")


@app.post("/api/events/{event_id}/agreement-text")
def agreement_text(event_id: str,file: UploadFile=File(...)):
    snapshot(event_id)
    content = file.file.read(4_000_001)
    if len(content)>4_000_000:
        raise HTTPException(413,"PDF must be smaller than 4 MB.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(415,"Upload a text-based PDF agreement.")
    try:
        result = subprocess.run([sys.executable,str(Path(__file__).with_name("read_pdf.py"))],
                                input=content,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=8,check=True)
    except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
        raise HTTPException(422,"The PDF could not be read. Paste its terms to continue.")
    text = result.stdout.decode().strip()
    if not text:
        raise HTTPException(422,"No selectable text found. Paste the agreement terms.")
    return {"text":text}


dist = ROOT / "frontend" / "dist"
if dist.is_dir():
    app.mount("/",StaticFiles(directory=dist,html=True),name="workspace")
