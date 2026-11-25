from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from clubos.main import app


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CLUBOS_DB", str(tmp_path / "workflow.sqlite3"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as client:
        assert client.post("/api/auth/demo").status_code == 200
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
    assert len(proposed["approvals"]) == len(original["approvals"]) + 1
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
    backup_drafts = [a for a in proposed["approvals"][0]["actions"] if a["type"] == "backup_outreach"]
    assert len(backup_drafts) == 2
    assert {a["prospect_id"] for a in backup_drafts} <= {
        s["prospect_id"] for s in applied["sponsors"] if s["stage"] == "Outreach Drafted"
    }
    assert all(t["status"] == "Blocked" for t in applied["tasks"] if t["sponsor_id"] and
               t["sponsor_id"] == next(s["id"] for s in applied["sponsors"] if s["name"] == "VectorForge"))

    with TestClient(app) as restarted:
        assert restarted.post("/api/auth/demo").status_code == 200
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


def test_bootstrap_stream_persists_scoped_specialist_steps(workspace):
    import json
    from clubos import trace
    from clubos.seed import CLUB

    response = workspace.post("/api/planning-jobs", json={
        "name": "Embedded Systems Lab", "type": "Hardware workshop", "target": 80,
        "initial_budget": 500_000, "sponsorship_target": 800_000, "goals": "Build low-power sensor projects."
    })
    assert response.status_code == 202, response.text
    job = response.json()["job_id"]
    feed = workspace.get(f"/api/jobs/{job}/trace")
    assert feed.headers["content-type"].startswith("text/event-stream")
    entries = [json.loads(line[6:]) for line in feed.text.splitlines() if line.startswith("data: ")]
    assert entries[0]["agent_name"] == "Nexus"
    assert entries[-2]["kind"] == "state_updated"
    assert entries[-1]["kind"] == "run_completed"
    assert {"Atlas", "Ledger", "Magnet", "Sentinel"} <= {
        row["agent_name"] for row in entries if row["kind"] == "handoff"
    }
    assert all(row["parent_run_id"] == entries[0]["run_id"] for row in entries if row["kind"] == "tool_called")
    assert any(row["latency_ms"] is not None for row in entries if row["kind"] == "tool_finished")
    event_id = workspace.get(f"/api/jobs/{job}").json()["id"]
    assert trace.entries(CLUB, "event_id", event_id) == entries
    data = Event(workspace, event_id).snapshot()
    assert data["metrics"]["planned"] == 1_300_000
    assert len([s for s in data["sponsors"] if s["stage"] == "Shortlisted" and s["draft"]]) == 2
    assert any(task["dependencies"] for task in data["tasks"])
    assert workspace.post("/api/auth/logout").status_code == 200
    assert workspace.get(f"/api/jobs/{job}/trace").status_code == 401


def test_confirmation_opens_receivable_and_saves_linked_work(workspace):
    from clubos import trace
    from clubos.seed import CLUB

    event = Event(workspace)
    initial = event.snapshot()
    partner = next(s for s in initial["sponsors"] if s["name"] == "Kernel Grove")
    event.action("sponsor_stage", {"sponsor_id": partner["id"], "stage": "Confirmed", "amount": 1_000_000},
                 request_id="confirm-kernel")
    final = event.snapshot()
    partner = next(s for s in final["sponsors"] if s["id"] == partner["id"])
    assert partner["stage"] == "Confirmed"
    assert partner["receivable"]["outstanding"] == 1_000_000
    assert partner["receivable"]["status"] == "Open"
    assert len(partner["deliverables"]) == 2
    linked = [t for t in final["tasks"] if t["sponsor_id"] == partner["id"]]
    assert sum(len(t["dependencies"]) for t in linked) == 1
    assert any(d["title"] == "Welcome Kernel Grove" for d in final["marketing"])
    assert final["metrics"]["committed"] - initial["metrics"]["committed"] == 1_000_000
    assert final["metrics"]["cash_balance"] == initial["metrics"]["cash_balance"]
    assert {"create_sponsor_receivable", "create_task", "draft_campaign"} <= {
        step["tool_name"] for step in trace.entries(CLUB, "event_id", event.id)
        if step["request_id"] == "confirm-kernel" and step["kind"] == "tool_finished"
    }


def test_overrun_and_copilot_proposals_are_editable_and_persisted(workspace):
    event = Event(workspace)
    initial = event.snapshot()
    assert initial["metrics"]["pending_approvals"] == 2
    assert len(initial["registration_history"]) == 14
    assert len({t["completed_at"][:10] for t in initial["tasks"] if t["completed_at"]}) > 2
    result = event.action("demo_overrun")
    proposed = event.snapshot()
    assert proposed["metrics"]["actual"] == initial["metrics"]["actual"] + 1_200_000
    assert proposed["metrics"]["shortfall"] > 0
    assert proposed["metrics"]["planned"] == initial["metrics"]["planned"]
    event.action("demo_overrun", expected=409)
    event.action("reject", {"approval_id": result["approval_id"]})
    result = event.action("copilot", {"question": "Cut ₹8k without touching prizes"})
    approval = next(a for a in event.snapshot()["approvals"] if a["id"] == result["approval_id"])
    cuts = [a for a in approval["actions"] if a["type"] == "reduce_budget"]
    assert sum(a["saving"] for a in cuts) == 800_000
    prizes = next(b for b in proposed["budget"] if b["category"] == "Prizes")
    assert prizes["id"] not in {a["category_id"] for a in cuts}
    event.action("edit_approval", {"approval_id": approval["id"], "index": 0, "amount": cuts[0]["saving"] - 100})
    event.action("approve", {"approval_id": approval["id"]})
    assert event.snapshot()["metrics"]["planned"] == initial["metrics"]["planned"] - 799_900
    followups = event.action("copilot", {"question": "Follow up with all contacted sponsors who haven’t replied"})
    assert followups["approval_id"]
    assert "Northloop Coffee" in followups["text"]
    blockers = event.action("copilot", {"question": "What are the biggest blockers?"})
    assert "Venue" in blockers["text"]


def test_provider_failure_uses_local_drafts_for_rest_of_recovery(workspace, monkeypatch):
    from clubos import intelligence

    attempts = []

    def unavailable(agent, context, fallback):
        attempts.append(agent)
        return {"text": fallback, "mode": "Deterministic fallback", "detail": "Rate limited"}

    monkeypatch.setattr(intelligence, "advise", unavailable)
    event = Event(workspace)
    result = event.action("demo_withdraw")
    assert result["mode"] == "Deterministic fallback"
    assert attempts == ["Magnet"]
    proposal = next(a for a in event.snapshot()["approvals"] if a["id"] == result["approval_id"])
    assert len([a for a in proposal["actions"] if a["type"] == "backup_outreach" and a["text"]]) == 2


def test_prompt_launch_registration_and_simulated_sponsor_lifecycle(workspace):
    from datetime import date, timedelta
    from clubos import trace
    from clubos.seed import CLUB

    start = date.today() + timedelta(days=18)
    reg = start - timedelta(days=5)
    job = workspace.post('/api/planning-jobs', json={
        'name': 'HackBlitz', 'start_date': str(start), 'end_date': str(start + timedelta(days=1)),
        'initial_budget': 1_500_000, 'target': 150,
        'brief': f'AI hackathon for teams of 2 to 4. Add a track and GitHub link. Registration closes {reg}. The total budget is ₹60,000.',
    }).json()['job_id']
    status = workspace.get(f'/api/jobs/{job}').json()
    assert status['status'] == 'completed'
    event = Event(workspace, status['id'])
    initial = event.snapshot()
    form = initial['registration_form']
    assert form['deadline'] == str(reg)
    assert {'track','github','team_size'} <= {f['key'] for f in form['fields']}
    assert initial['metrics']['planned'] == 6_000_000
    assert initial['event']['sponsorship_target'] == 4_500_000
    assert len(initial['tasks']) == len(initial['milestones']) == 8
    assert {s['agent_name'] for s in trace.entries(CLUB,'trace_id',job)} == {'Nexus','FormFlow','OpsLedger','Magnet'}
    public_url = '/api/registration/' + form['slug']
    assert workspace.get(public_url+'/qr.svg').headers['content-type'].startswith('image/svg+xml')
    with TestClient(app) as visitor:
        public = visitor.get(public_url).json()
        assert 'event_id' not in public and 'participants' not in public
        result = visitor.post(public_url, json={'name':'Ananya Das','email':'ananya@example.test','answers':{'track':'AI'}})
        assert result.status_code == 201, result.text
        assert visitor.get(event.url).status_code == 401
    after = event.snapshot()
    assert after['metrics']['registered'] == 1
    assert after['participants'][0]['answers'] == {'track':'AI'}
    pending = event.action('prepare_outreach')
    event.action('approve', {'approval_id':pending['approval_id']})
    partner = next(s for s in event.snapshot()['sponsors'] if s['stage']=='Contacted')
    offer = event.action('simulate_reply',{'sponsor_id':partner['id']})
    assert event.snapshot()['metrics']['committed'] == 0
    event.action('approve',{'approval_id':offer['approval_id']})
    final = event.snapshot()
    assert final['metrics']['committed'] > 0
    assert len([t for t in final['tasks'] if t['sponsor_id']==partner['id']]) == 2
    recovery = event.action('simulate_dropout')
    assert recovery['approval_id']
    assert event.snapshot()['metrics']['committed'] == 0
