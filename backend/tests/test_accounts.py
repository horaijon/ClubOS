from fastapi.testclient import TestClient

from clubos.main import app


def test_account_setup_and_data_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("CLUBOS_DB", str(tmp_path / "account.sqlite3"))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with TestClient(app) as client:
        assert client.get("/api/auth/session").json() == {"session": None}
        assert client.get("/api/events").status_code == 401
        assert client.get("/api/events/codestorm-2026/report.pdf").status_code == 401
        credentials = {"email": "organizer@example.test", "password": "a-local-test-password"}
        signup = client.post("/api/auth/signup", json={**credentials, "name": "Asha Menon"})
        assert signup.status_code == 201
        assert "HttpOnly" in signup.headers["set-cookie"]
        assert client.get("/api/events").status_code == 403
        details = {"name": "Robotics Society", "college": "RIT", "role": "Club Lead"}
        club = client.post("/api/auth/club", json=details)
        assert club.status_code == 201
        assert client.post("/api/auth/club", json=details).status_code == 409
        assert client.get("/api/events").json() == []
        assert client.get("/api/events/codestorm-2026").status_code == 404
        assert client.get("/api/events/codestorm-2026/report.pdf").status_code == 404
        job = client.post("/api/planning-jobs", json={"name": "Build night", "college": "RIT"}).json()
        plan = client.get("/api/jobs/" + job["job_id"]).json()
        assert plan["status"] == "completed"
        event_path = "/api/events/" + plan["id"]
        event = client.get(event_path).json()
        assert event["event"]["club"] == "Robotics Society"
        assert event["prospects"] == []
        assert [member["name"] for member in event["members"]] == ["Asha Menon"]
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get(event_path).status_code == 401
        assert client.post("/api/auth/demo").status_code == 200
        assert client.get("/api/events").json() == [{"id": "codestorm-2026", "name": "CodeStorm 2026"}]
        assert client.get(event_path).status_code == 404
        assert client.get(event_path + "/report.pdf").status_code == 404
        assert client.get("/api/jobs/" + job["job_id"]).status_code == 404
        assert client.post(event_path + "/actions", json={"type": "risk_scan", "request_id": "demo-test"}).status_code == 404
        assert client.post("/api/auth/club", json=details).status_code == 403
        assert client.post("/api/auth/login", json={**credentials, "password": "not-the-password"}).status_code == 401
        assert client.post("/api/auth/login", json=credentials).status_code == 200
        assert client.get("/api/events").json() == [{"id": plan["id"], "name": "Build night"}]
