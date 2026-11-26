"""Local demo entry point and bounded integration routes."""
import asyncio
from contextlib import asynccontextmanager, suppress
import hashlib
import logging
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
from . import api, auth, db, engine, forms_integration, gmail_integration, google_oauth, google_routes, poster_studio, trace, registration
from .seed import CLUB
from .reports import event_report

logger = logging.getLogger(__name__)


def sweep():
    with db.transaction() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM events")]
    for event_id in ids:
        try:
            engine.tick(event_id)
        except Exception:
            logger.exception("Reminder sweep failed for an event")


def google_sync_sweep():
    try:
        gmail_integration.poll_gmail_replies()
    except Exception:
        logger.exception("Gmail reply poll sweep failed")
    try:
        forms_integration.poll_form_responses()
    except Exception:
        logger.exception("Google Forms poll sweep failed")


async def reminders():
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(sweep)


async def google_poller():
    while True:
        await asyncio.sleep(18)
        await asyncio.to_thread(google_sync_sweep)


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    trace.initialize()
    trace.import_seed_history()
    with db.transaction(write=True) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS planning_jobs(
            job_id TEXT PRIMARY KEY,status TEXT NOT NULL,id TEXT,detail TEXT NOT NULL,
            input_hash TEXT NOT NULL,club_id TEXT REFERENCES clubs)""")
        if "club_id" not in {row["name"] for row in conn.execute("PRAGMA table_info(planning_jobs)")}:
            conn.execute("ALTER TABLE planning_jobs ADD COLUMN club_id TEXT REFERENCES clubs")
            conn.execute("UPDATE planning_jobs SET club_id=?", (CLUB,))
        conn.execute("UPDATE planning_jobs SET status='failed', detail='Server restarted during planning. Check Events before retrying.' WHERE status IN ('running','queued')")
    worker = asyncio.create_task(reminders())
    poller = asyncio.create_task(google_poller())
    try:
        yield
    finally:
        worker.cancel()
        poller.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        with suppress(asyncio.CancelledError):
            await poller


app = FastAPI(title="ClubOS",version="1.0",lifespan=lifespan)
from urllib.parse import urlsplit
public_host=urlsplit(os.getenv("CLUBOS_PUBLIC_URL","")).hostname
allowed_hosts=["localhost","127.0.0.1","testserver"]
if public_host:allowed_hosts.append(public_host)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
app.include_router(auth.router)
app.include_router(api.router)
app.include_router(registration.router)
app.include_router(google_oauth.router)
app.include_router(google_routes.router)
app.include_router(poster_studio.router)


@app.middleware("http")
async def local_writes(request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET","HEAD","OPTIONS"} and origin:
        if origin not in {str(request.base_url).rstrip("/"),"http://127.0.0.1:5173","http://localhost:5173"}:
            return JSONResponse({"detail":"This demo accepts changes from its local workspace."},status_code=403)
    if request.headers.get("content-length","").isdigit() and int(request.headers["content-length"]) > 4_500_000:
        return JSONResponse({"detail":"Maximum request size is 4 MB."},status_code=413)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    return {"status":"ready","gemini_configured":bool(os.getenv("GEMINI_API_KEY"))}


def run_planning(job_id, data, club):
    with db.transaction(write=True) as conn:
        conn.execute("UPDATE planning_jobs SET status='running',detail='Nexus is coordinating event planning.' WHERE job_id=?",(job_id,))
    try:
        execution=trace.Execution(club["id"],None,job_id,"Bootstrap event",job_id)
        with execution.recording(), db.transaction(True) as conn:
            result = engine.create(conn,data.model_dump(mode="json"),club["id"],execution)
            conn.execute("UPDATE planning_jobs SET status='completed',id=?,detail='Event plan saved.' WHERE job_id=?",
                         (result["id"],job_id))
    except Exception as exc:
        detail = str(exc.detail)[:400] if isinstance(exc,HTTPException) else "Planning failed. Review the event inputs and try again."
        logger.warning("Planning failed (%s)",type(exc).__name__)
        with db.transaction(write=True) as conn:
            conn.execute("UPDATE planning_jobs SET status='failed',detail=? WHERE job_id=? AND status='running'",(detail,job_id))



@app.post("/api/planning-jobs",status_code=202)
def start_planning(data: api.EventCreate, background: BackgroundTasks, club: auth.Workspace, idempotency_key: UUID | None=Header(None)):
    job_id = uuid5(NAMESPACE_URL, f"clubos:{club['id']}:{idempotency_key}").hex if idempotency_key else uuid4().hex
    fingerprint = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    with db.transaction(write=True) as conn:
        existing = conn.execute("SELECT input_hash FROM planning_jobs WHERE job_id=?",(job_id,)).fetchone()
        if existing:
            if existing["input_hash"] != fingerprint:
                raise HTTPException(409,"This planning request was already used for a different event.")
            return {"job_id":job_id}
        conn.execute("INSERT INTO planning_jobs(job_id,status,detail,input_hash,club_id) VALUES(?, 'queued', 'Waiting for Nexus.', ?, ?)",(job_id,fingerprint,club["id"]))
    background.add_task(run_planning,job_id,data,club)
    return {"job_id":job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, club: auth.Workspace):
    with db.transaction() as conn:
        row = conn.execute("SELECT job_id,status,id,detail FROM planning_jobs WHERE job_id=? AND club_id=?",(job_id,club["id"])).fetchone()
    if row is None:
        raise HTTPException(404,"Planning job not found.")
    return dict(row)


@app.get("/api/jobs/{job_id}/trace")
def job_trace(job_id:str, request:Request, club:auth.Workspace):
    status=job_status(job_id,club)
    if status["status"]=="failed" and not trace.entries(club["id"],"trace_id",job_id,limit=1):
        raise HTTPException(409,status["detail"])
    return trace.stream(request,club["id"],"trace_id",job_id)


def snapshot(event_id,club):
    with db.transaction() as conn:
        auth.authorize_event(conn,event_id,club["id"])
        return engine.workspace(conn,event_id)


def pdf_response(content, filename):
    return Response(content,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{filename}.pdf"'})


@app.get("/api/events/{event_id}/report.pdf")
def event_pdf(event_id: str,club: auth.Workspace):
    return pdf_response(event_report(snapshot(event_id,club)), "ClubOS-event-report")


@app.get("/api/events/{event_id}/sponsors/{sponsor_id}/report.pdf")
def sponsor_pdf(event_id: str,sponsor_id: str,club: auth.Workspace):
    state = snapshot(event_id,club)
    sponsor = next((s for s in state["sponsors"] if s["id"]==sponsor_id),None)
    if not sponsor:
        raise HTTPException(404,"Sponsor not found in this event.")
    return pdf_response(event_report(state,sponsor),"ClubOS-sponsor-report")


@app.post("/api/events/{event_id}/agreement-text")
def agreement_text(event_id: str,club: auth.Workspace,file: UploadFile=File(...)):
    snapshot(event_id,club)
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
    @app.get("/register/{slug}", include_in_schema=False)
    def registration_page(slug: str):
        return FileResponse(dist / "index.html")

    app.mount("/",StaticFiles(directory=dist,html=True),name="workspace")
