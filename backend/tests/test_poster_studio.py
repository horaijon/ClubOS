import io
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from clubos.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CLUBOS_DB", str(tmp_path / "poster_test.sqlite3"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as http:
        assert http.post("/api/auth/demo").status_code == 200
        yield http


def _png_bytes(color=(220, 40, 120)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


def test_poster_auto_generated_prompt_revised_and_uploaded(client, monkeypatch):
    from clubos import poster_studio
    monkeypatch.setattr(poster_studio, "_fetch_pollinations_background", lambda *a, **kw: (None, "image/jpeg"))
    eid = client.get("/api/events").json()[0]["id"]
    listed = client.get(f"/api/events/{eid}/posters").json()["posters"]
    assert len(listed) >= 1
    assert listed[0]["is_active"] is True

    img_res = client.get(listed[0]["image_url"])
    assert img_res.status_code == 200
    assert "CodeStorm 2026" in img_res.text

    # Prompt-based revision (robotic theme)
    robo = client.post(
        f"/api/events/{eid}/posters/generate",
        json={"prompt": "change theme to robotic"},
    )
    assert robo.status_code == 200, robo.text
    assert "Robotic" in robo.json()["poster"]["theme"]

    # Prompt-based revision (cyber neon + prize pool)
    rev = client.post(
        f"/api/events/{eid}/posters/generate",
        json={"prompt": "Switch to cyber neon dark theme with Prize Pool ₹50,000"},
    )
    assert rev.status_code == 200, rev.text
    poster = rev.json()["poster"]
    assert poster["theme"] == "Cyber Neon"
    rev_svg = client.get(poster["image_url"]).text
    assert "₹50,000" in rev_svg

    # Reference poster upload extracts palette & auto-generates
    ref_res = client.post(
        f"/api/events/{eid}/posters/upload",
        data={"mode": "reference", "prompt": "Match this palette"},
        files={"file": ("ref.png", _png_bytes((15, 95, 70)), "image/png")},
    )
    assert ref_res.status_code == 200, ref_res.text
    assert ref_res.json()["generated"] is not None

    # Final poster upload overrides active poster
    final_res = client.post(
        f"/api/events/{eid}/posters/upload",
        data={"mode": "final"},
        files={"file": ("final.png", _png_bytes((20, 30, 40)), "image/png")},
    )
    assert final_res.status_code == 200, final_res.text
    posters = final_res.json()["posters"]
    active = next(p for p in posters if p["is_active"])
    assert active["kind"] == "final"
    assert client.get(active["image_url"]).headers["content-type"] == "image/png"


def test_new_event_auto_generates_poster(client):
    start = (date.today() + timedelta(days=12)).isoformat()
    res = client.post(
        "/api/planning-jobs",
        json={
            "name": "AI HackFest",
            "type": "Hackathon",
            "college": "RIT",
            "venue": "Main Hall",
            "start_date": start,
            "end_date": start,
            "target": 120,
            "initial_budget": 100000,
            "brief": "24-hour AI hackathon with developer tracks.",
        },
    )
    assert res.status_code == 202
    job = client.get("/api/jobs/" + res.json()["job_id"]).json()
    assert job["status"] == "completed"
    posters = client.get(f"/api/events/{job['id']}/posters").json()["posters"]
    assert len(posters) >= 1
    assert "AI HackFest" in client.get(posters[0]["image_url"]).text


def test_ai_raster_poster_with_openai_and_reference(client, monkeypatch):
    import base64
    from unittest.mock import Mock
    from clubos import poster_studio

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    fake_png = _png_bytes((90, 40, 200))
    mock_resp = Mock(status_code=200, is_success=True)
    mock_resp.json.return_value = {"data": [{"b64_json": base64.b64encode(fake_png).decode("ascii")}]}
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return mock_resp

    monkeypatch.setattr(poster_studio.httpx, "post", post)

    eid = client.get("/api/events").json()[0]["id"]
    gen = client.post(f"/api/events/{eid}/posters/generate", json={"prompt": "Neon cyber robotics"})
    assert gen.status_code == 200, gen.text
    p = gen.json()["poster"]
    assert p["mime_type"] == "image/png"
    assert "OpenAI" in p["theme"]
    assert client.get(p["image_url"]).content == fake_png
    url, request = calls[-1]
    assert url.endswith("/images/generations")
    assert request["json"]["model"] == "gpt-image-2.5-flare"
    assert "Neon cyber robotics" in request["json"]["prompt"]
    event = client.get("/api/events").json()[0]
    assert event["name"] in request["json"]["prompt"]

    # Uploading a reference poster invokes images/edits
    ref = client.post(
        f"/api/events/{eid}/posters/upload",
        data={"mode": "reference", "prompt": "Match this exact cyberpunk look"},
        files={"file": ("ref.png", _png_bytes((20, 200, 180)), "image/png")},
    )
    assert ref.status_code == 200, ref.text
    assert ref.json()["generated"]["mime_type"] == "image/png"
    url, request = calls[-1]
    assert url.endswith("/images/edits")
    assert request["data"]["model"] == "gpt-image-2.5-flare"
    assert request["files"][0][0] == "image[]"


def test_ai_poster_generation_uses_reference_and_preserves_active_on_failure(client, monkeypatch):
    from clubos import poster_studio
    monkeypatch.setenv("OPENAI_API_KEY","test-key")
    eid = client.get("/api/events").json()[0]["id"]
    path = f"/api/events/{eid}/posters"
    source = _png_bytes()
    reference = client.post(path+'/upload', data={'mode':'reference','generate':'false'},
                            files={'file':('reference.png',source,'image/png')}).json()
    assert reference['generated'] is None
    calls = []

    def render(event, sponsors, deadline, reg_url, prompt, **kwargs):
        calls.append((prompt, kwargs['reference_bytes']))
        return _png_bytes((20,70,100)), 'Image provider test', ''

    monkeypatch.setattr(poster_studio, '_generate_ai_raster_poster', render)
    request = {'prompt':'Paper cutout illustration', 'require_ai':True}
    assert client.post(path+'/generate',json=request).status_code == 200
    request['reference_poster_id'] = reference['uploaded_id']
    result = client.post(path+'/generate',json=request)
    assert result.status_code == 200
    assert result.json()['poster']['mime_type'] == 'image/png'
    assert calls == [('Paper cutout illustration',None),('Paper cutout illustration',source)]
    before = client.get(path).json()
    monkeypatch.setattr(poster_studio,'_generate_ai_raster_poster',lambda *args,**kwargs:(None,'','quota'))
    assert client.post(path+'/generate',json=request).status_code == 502
    assert client.get(path).json() == before


def test_free_ai_poster_generation_with_hf_flux_and_verified_footer(client, monkeypatch):
    from clubos import poster_studio

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setattr(poster_studio, "_generate_hf_flux_image", lambda prompt: (_png_bytes((20, 180, 220)), "FLUX.1-schnell (Free AI)"))

    eid = client.get("/api/events").json()[0]["id"]
    res = client.post(
        f"/api/events/{eid}/posters/generate",
        json={"prompt": "Retro 80s synthwave neon arcade poster", "require_ai": True},
    )
    assert res.status_code == 200, res.text
    poster = res.json()["poster"]
    assert poster["mime_type"] == "image/png"
    assert "FLUX" in poster["theme"]
    img_res = client.get(poster["image_url"])
    assert img_res.status_code == 200
    assert img_res.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(img_res.content)) as im:
        assert im.size == (1080, 1350)


def test_cloudflare_workers_ai_poster_provider(client, monkeypatch):
    import base64
    from unittest.mock import Mock
    from clubos import poster_studio

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "cf-acc-123")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-tok-456")

    fake_png = _png_bytes((180, 90, 240))
    mock_resp = Mock(status_code=200, is_success=True, headers={"content-type": "application/json"})
    mock_resp.json.return_value = {"result": {"image": base64.b64encode(fake_png).decode("ascii")}}
    monkeypatch.setattr(poster_studio.httpx, "post", lambda *a, **kw: mock_resp)

    eid = client.get("/api/events").json()[0]["id"]
    res = client.post(
        f"/api/events/{eid}/posters/generate",
        json={"prompt": "Bauhaus minimalist geometric poster", "require_ai": True},
    )
    assert res.status_code == 200, res.text
    assert "Cloudflare" in res.json()["poster"]["theme"]
    assert res.json()["poster"]["mime_type"] == "image/png"
