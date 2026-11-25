from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from clubos import intelligence
from clubos.main import app


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv("CLUBOS_DB", str(tmp_path/"integration.sqlite3"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as http:
        yield http


def test_advice_survives_provider_failure(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY","test-only")
    provider = Mock()
    provider.models.generate_content.side_effect = TimeoutError()
    monkeypatch.setattr(intelligence, "_client", lambda:provider)
    result = intelligence.advise("Atlas",{"event":"Workshop"},"Assign a venue lead.")
    assert result["mode"]=="Deterministic fallback" and result["text"]=="Assign a venue lead."


def test_fallback_terms_keep_multiple_amounts_uncertain(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY",raising=False)
    result = intelligence.extract_terms("INR 15,000 or INR 25,000 for a booth.","agreement")
    assert result["amount"] is None
    assert result["deliverables"]


def test_pdf_export_and_extraction(client):
    event = client.get("/api/events").json()[0]["id"]
    base = f"/api/events/{event}"
    result = client.get(base+"/report.pdf")
    assert result.status_code==200
    pages = PdfReader(BytesIO(result.content)).pages
    assert "CodeStorm 2026" in pages[0].extract_text()
    assert "65,000" in " ".join(p.extract_text() for p in pages)
    source = Path(__file__).resolve().parents[2]/"demo/sample_agreement.pdf"
    extracted = client.post(base+"/agreement-text",files={"file":("sample.pdf",source.read_bytes(),"application/pdf")})
    assert "Kernel Grove" in extracted.json()["text"]
    rejected = client.post(base+"/agreement-text",files={"file":("bad.pdf",b"not a pdf","application/pdf")})
    assert rejected.status_code==415
    assert client.get(base+"/sponsors/missing/report.pdf").status_code==404


def test_persisted_planning_job(client):
    start = (date.today()+timedelta(days=10)).isoformat()
    event = dict(name="Build clinic",type="Workshop",description="Hands-on clinic",college="RIT",
                 venue="Hall",start_date=start,end_date=start,target=80,initial_budget=200000,
                 sponsorship_target=100000,goals="Teach prototyping.")
    headers = {"Idempotency-Key":"0c4cf6d6-b32b-41f6-82dd-4edd762f3802"}
    submitted = client.post("/api/planning-jobs",json=event,headers=headers)
    assert submitted.status_code==202, submitted.text
    assert client.post("/api/planning-jobs",json=event,headers=headers).json() == submitted.json()
    assert client.post("/api/planning-jobs",json=dict(event,name="Other"),headers=headers).status_code == 409
    job = client.get("/api/jobs/"+submitted.json()["job_id"]).json()
    assert job["status"]=="completed", job
    data = client.get("/api/events/"+job["id"]).json()
    assert data["tasks"] and data["runs"] and data["budget"]


def test_external_origin_cannot_write(client):
    assert client.post("/api/events",json={},headers={"Origin":"https://other.example"}).status_code==403
