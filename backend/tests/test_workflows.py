from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from clubos.main import app


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CLUBOS_DB", str(tmp_path / "workflow.sqlite3"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as client:
        yield client


class Event:
    def __init__(self, client, event_id=None):
        self.client = client
        self.id = event_id or client.get("/api/events").json()[0]["id"]
        self.url = f"/api/events/{self.id}"

    def snapshot(self):
        response = self.client.get(self.url)
        assert response.status_code == 200, response.text
        return response.json()

    def action(self, name, payload=None, request_id=None, expected=200):
        response = self.client.post(
            self.url + "/actions",
            json={"type": name, "payload": payload or {}, "request_id": request_id or uuid4().hex},
        )
        assert response.status_code == expected, response.text
        return response.json()


def test_withdrawal_approval_and_idempotency(workspace):
    event = Event(workspace)
    original = event.snapshot()
    assert original["metrics"]["projected_funding"] == 6_500_000
    assert original["metrics"]["planned"] == 6_000_000
    plan = event.action("demo_withdraw", request_id="withdraw")
    assert plan == event.action("demo_withdraw", request_id="withdraw")
    event.action("risk_scan", request_id="withdraw", expected=409)
    proposed = event.snapshot()
    assert proposed["metrics"]["projected_funding"] == 4_500_000
    assert proposed["metrics"]["shortfall"] == 1_500_000
    assert proposed["metrics"]["received"] == original["metrics"]["received"]
    assert proposed["budget"] == original["budget"]
    assert len(proposed["approvals"]) == 1
    assert {"Sentinel", "Nexus", "Ledger", "Magnet", "Atlas"} <= {
        run["agent"] for run in proposed["runs"] if run["workflow_id"] == plan["workflow_id"]
    }

    decision = {"approval_id": plan["approval_id"]}
    event.action("approve", decision, request_id="accept")
    event.action("approve", decision, request_id="accept")
    event.action("approve", decision, expected=409)
    applied = event.snapshot()
    assert applied["approvals"][0]["status"] == "Approved"
    assert applied["metrics"]["planned"] < proposed["metrics"]["planned"]
    assert applied["metrics"]["projected_funding"] == proposed["metrics"]["projected_funding"]
    assert len(applied["tasks"]) == len(proposed["tasks"]) + 1
    assert len(applied["sponsors"]) == len(proposed["sponsors"]) + 1

    with TestClient(app) as restarted:
        assert Event(restarted, event.id).snapshot()["metrics"] == applied["metrics"]


def test_rejection_preserves_tasks_and_budget(workspace):
    event = Event(workspace)
    plan = event.action("demo_withdraw")
    before = event.snapshot()
    event.action("reject", {"approval_id": plan["approval_id"]})
    after = event.snapshot()
    assert after["approvals"][0]["status"] == "Rejected"
    for key in ("tasks", "sponsors", "budget"):
        assert before[key] == after[key]


def test_sponsor_matching_drafts_and_event_scope(workspace):
    event = Event(workspace)
    prospect = event.snapshot()["prospects"][0]
    assert 0 < prospect["score"] <= 100 and prospect["reason"]
    payload = {"prospect_id": prospect["id"]}
    sponsor = event.action("add_prospect", payload)["sponsor_id"]
    assert event.action("add_prospect", payload)["sponsor_id"] == sponsor
    draft = event.action("outreach", {"sponsor_id": sponsor})
    assert prospect["name"] in draft["text"] and draft["mode"] == "Deterministic fallback"
    new_event = workspace.post("/api/events",json={"name":"Robotics Workshop","type":"Workshop"})
    assert new_event.status_code == 201
    Event(workspace, new_event.json()["id"]).action("outreach", {"sponsor_id": sponsor}, expected=404)


def test_conditional_offer_and_reviewed_agreement(workspace):
    event = Event(workspace)
    before = event.snapshot()
    response = event.action("demo_response")
    assert response["terms"]["amount"] == 2_500_000
    assert response["terms"]["conditions"]
    event.action("approve", {"approval_id": response["approval_id"]})
    assert event.snapshot()["metrics"]["committed"] == before["metrics"]["committed"]

    agreement = event.action("demo_agreement")
    assert agreement["terms"]["deliverables"]
    event.action("approve", {"approval_id": agreement["approval_id"]})
    after = event.snapshot()
    assert after["metrics"]["committed"] == before["metrics"]["committed"] + 2_500_000
    assert after["metrics"]["received"] == before["metrics"]["received"]
    sponsor = next(row for row in after["sponsors"] if row["name"] == "Kernel Grove")
    assert sponsor["deliverables"]
    assert all(row["owner"] for row in sponsor["deliverables"])


def test_delayed_task_and_registered_campaign(workspace):
    event = Event(workspace)
    delayed = event.action("demo_delay")
    before = event.snapshot()
    plan = next(r for r in before["approvals"] if r["id"] == delayed["approval_id"])
    moves = [a for a in plan["actions"] if a["type"] == "move_deadline"]
    assert len(moves) > 1
    event.action("approve", {"approval_id": delayed["approval_id"]})
    tasks = {t["id"]: t for t in event.snapshot()["tasks"]}
    assert all(tasks[a["task_id"]]["due_date"] == a["after"] for a in moves)
    marketing = event.action("demo_registration")
    event.action("approve", {"approval_id": marketing["approval_id"]})
    assert any(a["title"] == "Campus registration drive" for a in event.snapshot()["marketing"])


def test_invalid_event_dates_and_dependency_cycle(workspace):
    invalid = workspace.post("/api/events",json={"name":"Invalid","start_date":"2027-02-07","end_date":"2027-02-06"})
    assert invalid.status_code == 422
    event = Event(workspace)
    task = event.snapshot()["tasks"][0]
    event.action("update_task",{"task_id":task["id"],"dependencies":[task["id"]]},expected=422)
    assert event.snapshot()["tasks"][0] == task
