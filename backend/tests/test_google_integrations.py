from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from clubos import db, forms_integration, gmail_integration, google_oauth
from clubos.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CLUBOS_DB", str(tmp_path / "google_test.sqlite3"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8017/api/integrations/google/callback")
    with TestClient(app) as http:
        assert http.post("/api/auth/demo").status_code == 200
        yield http


def test_google_oauth_status_and_disconnect(client):
    res = client.get("/api/integrations/google/status")
    assert res.status_code == 200
    assert res.json() == {"connected": False, "email": None, "available": True}

    auth_res = client.get("/api/integrations/google/auth-url")
    assert auth_res.status_code == 200
    url = auth_res.json()["url"]
    assert "accounts.google.com" in url
    assert "forms.body" in url
    assert "gmail.send" in url

    google_oauth._store_tokens(
        club_id="nexus-technical-club",
        access_token="access-123",
        refresh_token="refresh-456",
        token_expiry=None,
        email="club@example.edu",
        scopes=google_oauth.SCOPES,
    )
    res2 = client.get("/api/integrations/google/status")
    assert res2.json() == {"connected": True, "email": "club@example.edu", "available": True}

    disc = client.post("/api/integrations/google/disconnect")
    assert disc.status_code == 200
    assert client.get("/api/integrations/google/status").json()["connected"] is False


def test_gmail_send_and_reply_tracking_creates_approval(client, monkeypatch):
    google_oauth._store_tokens(
        club_id="nexus-technical-club",
        access_token="access-123",
        refresh_token="refresh-456",
        token_expiry=None,
        email="club@example.edu",
        scopes=google_oauth.SCOPES,
    )

    events = client.get("/api/events").json()
    eid = events[0]["id"]

    # Add a real demo sponsor
    add_res = client.post(
        f"/api/events/{eid}/actions",
        json={
            "type": "add_demo_sponsor",
            "payload": {"name": "Judge Tech", "contact_email": "judge@example.com"},
            "request_id": "req-add-demo-1",
        },
    )
    assert add_res.status_code == 200, add_res.text
    sponsor_id = add_res.json()["sponsor_id"]

    # Mock Gmail service for sending and thread reply fetching
    import base64
    reply_body = base64.urlsafe_b64encode(
        b"Looks great! We will sponsor \xe2\x82\xb925,000 for Gold Tier and need a partner booth and logo."
    ).decode("ascii")

    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {
        "id": "gmail-msg-1",
        "threadId": "gmail-thread-1",
    }
    mock_service.users().threads().get().execute.return_value = {
        "id": "gmail-thread-1",
        "messages": [
            {
                "id": "gmail-msg-1",
                "payload": {"headers": [{"name": "From", "value": "club@example.edu"}]},
            },
            {
                "id": "gmail-msg-2",
                "internalDate": "1900000000000",
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "Judge <judge@example.com>"},
                        {"name": "Subject", "value": "Re: CodeStorm 2026"},
                    ],
                    "body": {"data": reply_body},
                },
            },
        ],
    }
    monkeypatch.setattr(gmail_integration, "_get_gmail_service", lambda _cid: mock_service)

    send_res = client.post(
        f"/api/events/{eid}/sponsors/{sponsor_id}/send-email",
        json={"to_email": "judge@example.com", "subject": "CodeStorm Gold Pitch", "body": "Join us!"},
    )
    assert send_res.status_code == 200, send_res.text
    assert send_res.json()["thread_id"] == "gmail-thread-1"

    # Check replies now
    rep_res = client.post(f"/api/events/{eid}/check-replies")
    assert rep_res.status_code == 200, rep_res.text
    data = rep_res.json()
    assert data["count"] == 1
    assert data["replies"][0]["amount"] == 2500000

    # Verify approval card created and email history populated
    snap = client.get(f"/api/events/{eid}").json()
    assert any("25,000" in a["title"] and a["status"] == "Pending" for a in snap["approvals"])
    hist = client.get(f"/api/events/{eid}/sponsors/{sponsor_id}/emails").json()["emails"]
    assert len(hist) == 2
    assert hist[0]["direction"] == "outbound"
    assert hist[1]["direction"] == "inbound"


def test_google_form_creation_and_live_response_sync(client, monkeypatch):
    google_oauth._store_tokens(
        club_id="nexus-technical-club",
        access_token="access-123",
        refresh_token="refresh-456",
        token_expiry=None,
        email="club@example.edu",
        scopes=google_oauth.SCOPES,
    )
    events = client.get("/api/events").json()
    eid = events[0]["id"]

    mock_forms = MagicMock()
    mock_forms.forms().create().execute.return_value = {
        "formId": "g-form-xyz",
        "responderUri": "https://docs.google.com/forms/d/e/g-form-xyz/viewform",
    }
    mock_forms.forms().batchUpdate().execute.return_value = {}
    mock_forms.forms().get().execute.return_value = {
        "items": [
            {"title": "Full Name", "questionItem": {"question": {"questionId": "q1"}}},
            {"title": "Email", "questionItem": {"question": {"questionId": "q2"}}},
            {"title": "Track / Domain", "questionItem": {"question": {"questionId": "q3"}}},
            {"title": "College name", "questionItem": {"question": {"questionId": "q4"}}},
            {"title": "Department name", "questionItem": {"question": {"questionId": "q5"}}},
        ]
    }
    mock_forms.forms().responses().list().execute.return_value = {
        "responses": [
            {
                "responseId": "resp-001",
                "answers": {
                    "q1": {"textAnswers": {"answers": [{"value": "Priya Sharma"}]}},
                    "q2": {"textAnswers": {"answers": [{"value": "priya@college.edu"}]}},
                    "q3": {"textAnswers": {"answers": [{"value": "AI & Agents"}]}},
                    "q4": {"textAnswers": {"answers": [{"value": "RIT"}]}},
                    "q5": {"textAnswers": {"answers": [{"value": "Computer Science"}]}},
                },
            }
        ]
    }
    monkeypatch.setattr(forms_integration, "_get_forms_service", lambda _cid: mock_forms)

    create_res = client.post(f"/api/events/{eid}/create-google-form", json={})
    assert create_res.status_code == 200, create_res.text
    assert create_res.json()["responder_uri"] == "https://docs.google.com/forms/d/e/g-form-xyz/viewform"

    qr_res = client.get(f"/api/events/{eid}/google-form/qr.svg")
    assert qr_res.status_code == 200
    assert "<svg" in qr_res.text

    sync_res = client.post(f"/api/events/{eid}/sync-form-responses")
    assert sync_res.status_code == 200
    assert sync_res.json()["new_count"] == 1

    # Second sync deduplicates
    sync_res2 = client.post(f"/api/events/{eid}/sync-form-responses")
    assert sync_res2.json()["new_count"] == 0

    snap = client.get(f"/api/events/{eid}").json()
    assert snap["registration_form"]["is_google_form"] is True
    participant = next(p for p in snap["participants"] if p["email"] == "priya@college.edu")
    assert participant["answers"]["college_name"] == "RIT"
    assert participant["answers"]["department_name"] == "Computer Science"
    assert participant["answers"]["track_domain"] == "AI & Agents"


def test_suggested_questions_always_ask_for_track(monkeypatch):
    from clubos import intelligence

    def without_track(_agent, _payload, schema, _fallback):
        return schema(questions=[{"title": "Team Name"}]), None, None

    monkeypatch.setattr(intelligence, "structured", without_track)
    titles = [q["title"] for q in forms_integration.suggest_questions("Hack Night", "Hackathon", "")]
    assert titles.count("Track / Domain") == 1


def test_outreach_list_discover_and_bulk_send(client, monkeypatch):
    google_oauth._store_tokens(
        club_id="nexus-technical-club",
        access_token="access-123",
        refresh_token="refresh-456",
        token_expiry=None,
        email="club@example.edu",
        scopes=google_oauth.SCOPES,
    )
    eid = client.get("/api/events").json()[0]["id"]

    # Add two real demo contacts
    for idx, (name, email) in enumerate([("Alpha Corp", "alpha@example.com"), ("Beta Labs", "beta@example.com")]):
        r = client.post(
            f"/api/events/{eid}/actions",
            json={"type": "add_demo_sponsor", "payload": {"name": name, "contact_email": email}, "request_id": f"bulk-add-{idx}"},
        )
        assert r.status_code == 200

    # Discover all contacts & specialized drafts (real companies + emails)
    disc = client.post(f"/api/events/{eid}/outreach-list/discover")
    assert disc.status_code == 200, disc.text
    items = disc.json()["items"]
    assert len(items) >= 2
    assert all(i["subject"] and i["body"] for i in items)
    assert any(i.get("contact_email") and "@" in i["contact_email"] and i.get("website") for i in items)

    # Filter to our two contacts and customize one subject/body, then send all in 1 click
    ready = [i for i in items if i["contact_email"] in ("alpha@example.com", "beta@example.com")]
    assert len(ready) == 2
    ready[0]["subject"] = "Edited Gold Subject"

    sent_calls = []
    def fake_send(club_id, event_id, sponsor_id, to_email, subject, body, thread_id=None, conn=None):
        sent_calls.append((to_email, subject))
        return {"id": f"id-{len(sent_calls)}", "message_id": f"m-{len(sent_calls)}", "thread_id": f"t-{len(sent_calls)}", "sent_at": "2026-11-26T00:00:00Z"}

    monkeypatch.setattr(gmail_integration, "send_sponsor_email", fake_send)

    blast = client.post(
        f"/api/events/{eid}/outreach-list/send-all",
        json={
            "items": [
                {"sponsor_id": i["sponsor_id"], "to_email": i["contact_email"], "subject": i["subject"], "body": i["body"]}
                for i in ready
            ]
        },
    )
    assert blast.status_code == 200, blast.text
    assert blast.json()["sent_count"] == 2
    assert ("alpha@example.com", "Edited Gold Subject") in sent_calls or ("beta@example.com", "Edited Gold Subject") in sent_calls


def test_same_google_identity_keeps_club_accounts_isolated(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit

    def fake_flow(state=None):
        return SimpleNamespace(
            authorization_url=lambda **kwargs:(f'https://accounts.google.com/o/oauth2/auth?state={state}', state),
            fetch_token=lambda **kwargs:None,
            credentials=SimpleNamespace(token=f'token-{state}',refresh_token='refresh',
                expiry=datetime.now(timezone.utc)+timedelta(hours=1),scopes=google_oauth.SCOPES),
        )

    service=MagicMock()
    service.users.return_value.getProfile.return_value.execute.return_value={'emailAddress':'same-google@example.test'}
    monkeypatch.setattr(google_oauth,'_build_flow',fake_flow)
    monkeypatch.setattr(google_oauth,'build',lambda *args,**kwargs:service)

    def signup(browser, email):
        assert browser.post('/api/auth/signup',json={'name':'Organizer','email':email,'password':'test-password-123'}).status_code==201
        assert browser.post('/api/auth/club',json={'name':email,'college':'Campus'}).status_code==201

    def start(browser):
        url=browser.get('/api/integrations/google/auth-url').json()['url']
        return parse_qs(urlsplit(url).query)['state'][0]

    def connect(browser,state):
        return browser.get('/api/integrations/google/callback',params={'code':'test-code','state':state},follow_redirects=False).headers['location']

    with TestClient(app) as first, TestClient(app) as second:
        signup(first,'first@example.test')
        signup(second,'second@example.test')
        state=start(first)
        assert 'no_session' in connect(second,state)
        assert 'success' in connect(first,state)
        created=first.post('/api/events',json={'name':'First account event'}).json()
        assert second.get('/api/events').json()==[]
        assert 'success' in connect(second,start(second))
        assert second.get('/api/integrations/google/status').json()['email']==first.get('/api/integrations/google/status').json()['email']
        assert second.get('/api/events/'+created['id']).status_code==404
        assert second.get('/api/events').json()==[]
        second.post('/api/integrations/google/disconnect')
        assert first.get('/api/integrations/google/status').json()['connected']


def test_sign_in_with_google_connects_the_club(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit

    def fake_flow(state=None):
        return SimpleNamespace(
            authorization_url=lambda **kwargs: (f"https://accounts.google.com/o/oauth2/auth?state={state}", state),
            fetch_token=lambda **kwargs: None,
            credentials=SimpleNamespace(token="token", refresh_token="refresh", scopes=google_oauth.SCOPES,
                                        expiry=datetime.now(timezone.utc) + timedelta(hours=1)),
        )

    who = {"sub": "google-1", "email": "new@example.test", "name": "New Organizer"}
    monkeypatch.setattr(google_oauth, "_build_flow", fake_flow)
    monkeypatch.setattr(google_oauth, "_identity", lambda creds: dict(who))
    base = "http://localhost:8017"

    def sign_in(browser, callback_browser=None):
        res = browser.get("/api/integrations/google/login", follow_redirects=False)
        state = parse_qs(urlsplit(res.headers["location"]).query)["state"][0]
        return (callback_browser or browser).get(
            "/api/integrations/google/callback", params={"code": "c", "state": state},
            follow_redirects=False).headers["location"]

    with TestClient(app, base_url=base) as browser, TestClient(app, base_url=base) as other:
        # A callback opened in a different browser is refused.
        assert "google_login=error" in sign_in(browser, other)
        # First sign-in creates the account; creating the club connects Google.
        assert sign_in(browser) == "/#setup"
        assert browser.post("/api/auth/club", json={"name": "Club", "college": "Campus"}).status_code == 201
        assert browser.get("/api/integrations/google/status").json()["email"] == "new@example.test"
        browser.post("/api/integrations/google/disconnect")
        browser.post("/api/auth/logout")
        # Signing in again reconnects automatically.
        assert sign_in(browser) == "/#dashboard"
        assert browser.get("/api/integrations/google/status").json()["connected"]

        # An unverified password account is never taken over by email match alone.
        assert other.post("/api/auth/signup", json={
            "name": "Someone", "email": "taken@example.test", "password": "test-password-123"}).status_code == 201
        other.post("/api/auth/logout")
        who.update(sub="google-2", email="taken@example.test")
        assert "link_required" in sign_in(other)
        assert other.get("/api/auth/session").json()["session"] is None
        # Connecting once while logged in links it.
        other.post("/api/auth/login", json={"email": "taken@example.test", "password": "test-password-123"})
        assert other.post("/api/auth/club", json={"name": "Other", "college": "Campus"}).status_code == 201
        url = other.get("/api/integrations/google/auth-url").json()["url"]
        monkeypatch.setattr(google_oauth, "build", lambda *args, **kwargs: MagicMock(**{
            "users.return_value.getProfile.return_value.execute.return_value": {"emailAddress": "taken@example.test"}}))
        other.get("/api/integrations/google/callback", params={
            "code": "c", "state": parse_qs(urlsplit(url).query)["state"][0]}, follow_redirects=False)
        other.post("/api/auth/logout")
        assert sign_in(other) == "/#dashboard"
