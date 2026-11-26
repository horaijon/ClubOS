"""Google Forms integration: real form creation, live response sync, and QR codes."""
import logging
import re

from . import db

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS google_forms (
    id             TEXT PRIMARY KEY,
    event_id       TEXT NOT NULL REFERENCES events ON DELETE CASCADE,
    google_form_id TEXT NOT NULL,
    responder_uri  TEXT NOT NULL,
    edit_uri       TEXT NOT NULL,
    club_id        TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    UNIQUE(event_id)
);
CREATE TABLE IF NOT EXISTS google_form_responses (
    response_id    TEXT PRIMARY KEY,
    event_id       TEXT NOT NULL REFERENCES events ON DELETE CASCADE,
    participant_id TEXT REFERENCES participants ON DELETE SET NULL,
    synced_at      TEXT NOT NULL
);
"""


def _get_forms_service(club_id: str):
    """Return an authenticated Google Forms API client for *club_id*."""
    try:
        from . import google_oauth
    except ImportError as exc:
        raise RuntimeError("Google OAuth module is not available.") from exc
    service = google_oauth.get_forms_service(club_id)
    if service is None:
        raise RuntimeError("Google account is not connected.")
    return service


def _question_request(index: int, q: dict) -> dict:
    """Build a single ``createItem`` request for Forms batchUpdate."""
    q_type = q.get("type", "text").lower()
    required = bool(q.get("required", False))

    if q_type in ("multiple_choice", "dropdown", "checkbox"):
        choice_type_map = {
            "multiple_choice": "RADIO",
            "dropdown": "DROP_DOWN",
            "checkbox": "CHECKBOX",
        }
        options = [str(opt).strip() for opt in (q.get("options") or ["Option 1"]) if str(opt).strip()]
        if not options:
            options = ["Option 1"]
        question_item = {
            "question": {
                "required": required,
                "choiceQuestion": {
                    "type": choice_type_map[q_type],
                    "options": [{"value": opt} for opt in options],
                },
            }
        }
    elif q_type == "paragraph":
        question_item = {
            "question": {
                "required": required,
                "textQuestion": {"paragraph": True},
            }
        }
    else:
        question_item = {
            "question": {
                "required": required,
                "textQuestion": {"paragraph": False},
            }
        }

    return {
        "createItem": {
            "item": {
                "title": q.get("title", "Question"),
                "questionItem": question_item,
            },
            "location": {"index": index},
        }
    }


def _build_description(event_data: dict) -> str:
    """Build a human-readable description from event metadata."""
    parts: list[str] = []
    if event_data.get("start_date"):
        parts.append(f"Date: {event_data['start_date']}")
    if event_data.get("end_date") and event_data["end_date"] != event_data.get("start_date"):
        parts.append(f"End: {event_data['end_date']}")
    if event_data.get("venue"):
        parts.append(f"Venue: {event_data['venue']}")
    if event_data.get("deadline"):
        parts.append(f"Registration deadline: {event_data['deadline']}")
    if event_data.get("description"):
        parts.append(f"\n{event_data['description']}")
    return "\n".join(parts)


def create_google_form(
    club_id: str,
    event_id: str,
    event_name: str,
    event_data: dict,
    questions: list[dict] | None = None,
    conn=None,
) -> dict:
    """Create a real Google Form for an event and persist its metadata."""
    service = _get_forms_service(club_id)

    form_body = {"info": {"title": f"{event_name} — Registration", "documentTitle": f"{event_name} — Registration"}}
    created = service.forms().create(body=form_body).execute()
    form_id: str = created["formId"]

    requests: list[dict] = []
    description = _build_description(event_data)
    if description:
        requests.append({
            "updateFormInfo": {
                "info": {"description": description},
                "updateMask": "description",
            }
        })

    default_questions = [
        {"title": "Full Name", "type": "text", "required": True},
        {"title": "Email", "type": "text", "required": True},
    ]
    extra = [
        q for q in (questions or [])
        if q.get("title", "").strip().lower() not in {"full name", "name", "email", "email address"}
    ]
    all_questions = default_questions + extra

    for idx, q in enumerate(all_questions):
        requests.append(_question_request(idx, q))

    if requests:
        service.forms().batchUpdate(
            formId=form_id,
            body={"requests": requests},
        ).execute()

    responder_uri = created.get("responderUri") or f"https://docs.google.com/forms/d/{form_id}/viewform"
    edit_uri = f"https://docs.google.com/forms/d/{form_id}/edit"

    def _persist(c):
        c.execute(
            """INSERT INTO google_forms (id, event_id, google_form_id,
               responder_uri, edit_uri, club_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(event_id) DO UPDATE SET
                 google_form_id = excluded.google_form_id,
                 responder_uri  = excluded.responder_uri,
                 edit_uri       = excluded.edit_uri,
                 created_at     = excluded.created_at""",
            (db.uid(), event_id, form_id, responder_uri, edit_uri, club_id, db.now()),
        )
        wid = db.insert(
            c,
            "workflows",
            event_id=event_id,
            trigger="google_form_created",
            request_id=f"google-form:{form_id}",
            input_hash=form_id,
            result="{}",
            created_at=db.now(),
        )
        summary = f"FormFlow published Google Form with {len(all_questions)} questions."
        db.insert(
            c,
            "runs",
            event_id=event_id,
            workflow_id=wid,
            agent="FormFlow",
            trigger="google_form_created",
            tool="publish_registration",
            summary=summary,
            mode="Google Forms API",
            status="Completed",
            created_at=db.now(),
        )
        db.insert(
            c,
            "activity",
            event_id=event_id,
            title="Google Form published",
            description=summary,
            agent="FormFlow",
            created_at=db.now(),
        )

    if conn is not None:
        _persist(conn)
    else:
        with db.transaction(write=True) as c:
            _persist(c)

    logger.info("Created Google Form %s for event %s (%s)", form_id, event_id, responder_uri)
    return {
        "form_id": form_id,
        "responder_uri": responder_uri,
        "edit_uri": edit_uri,
        "question_count": len(all_questions),
    }


def _normalize_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def sync_form_responses(club_id: str, event_id: str) -> int:
    """Fetch new Google Form responses and insert them as participants."""
    with db.transaction() as conn:
        gf = conn.execute(
            "SELECT google_form_id FROM google_forms WHERE event_id=? AND club_id=?",
            (event_id, club_id),
        ).fetchone()
    if gf is None:
        return 0

    google_form_id: str = gf["google_form_id"]
    service = _get_forms_service(club_id)

    result = service.forms().responses().list(formId=google_form_id).execute()
    responses: list[dict] = result.get("responses", [])
    if not responses:
        return 0

    form_detail = service.forms().get(formId=google_form_id).execute()
    question_map: dict[str, str] = {}
    for item in form_detail.get("items", []):
        qi = item.get("questionItem")
        if qi and qi.get("question"):
            qid = qi["question"].get("questionId")
            if qid:
                question_map[qid] = item.get("title", "")

    new_count = 0
    added_names: list[str] = []

    with db.transaction(write=True) as conn:
        for resp in responses:
            response_id: str = resp.get("responseId", "")
            if not response_id:
                continue

            existing = conn.execute(
                "SELECT 1 FROM google_form_responses WHERE response_id=?",
                (response_id,),
            ).fetchone()
            if existing:
                continue

            answers_raw: dict = resp.get("answers", {})
            answer_map: dict[str, str] = {}
            extra_answers: dict[str, str] = {}
            name = ""
            email = ""

            for qid, ans_obj in answers_raw.items():
                title = question_map.get(qid, qid)
                text_answers = ans_obj.get("textAnswers", {}).get("answers", [])
                value = ", ".join(a.get("value", "") for a in text_answers if a.get("value")).strip()
                answer_map[title] = value
                lower_title = title.lower()
                if not name and ("full name" in lower_title or lower_title == "name"):
                    name = value
                elif not email and "email" in lower_title:
                    email = value.lower()
                elif value:
                    extra_answers[_normalize_key(title)] = value

            if not email and resp.get("respondentEmail"):
                email = resp["respondentEmail"].strip().lower()
            if not name and email:
                name = email.split("@", 1)[0]

            if not name or not email:
                conn.execute(
                    "INSERT OR IGNORE INTO google_form_responses (response_id, event_id, participant_id, synced_at) VALUES (?,?,?,?)",
                    (response_id, event_id, None, db.now()),
                )
                continue

            dup = conn.execute(
                "SELECT id FROM participants WHERE event_id=? AND email=?",
                (event_id, email),
            ).fetchone()
            if dup:
                pid = dup["id"]
            else:
                pid = db.insert(
                    conn,
                    "participants",
                    event_id=event_id,
                    name=name[:120],
                    email=email[:254],
                    created_at=db.now(),
                )
                if extra_answers:
                    conn.execute(
                        "INSERT OR REPLACE INTO registration_answers (participant_id, answers) VALUES (?, ?)",
                        (pid, db.encode(extra_answers)),
                    )
                new_count += 1
                added_names.append(name[:60])

            conn.execute(
                "INSERT OR IGNORE INTO google_form_responses (response_id, event_id, participant_id, synced_at) VALUES (?,?,?,?)",
                (response_id, event_id, pid, db.now()),
            )

        if new_count:
            names_preview = ", ".join(added_names[:3]) + (f" +{new_count - 3} more" if new_count > 3 else "")
            summary = f"FormFlow synced {new_count} new Google Form registration{'s' if new_count != 1 else ''} ({names_preview})."
            wid = db.insert(
                conn,
                "workflows",
                event_id=event_id,
                trigger="google_form_sync",
                request_id=f"form-sync:{db.uid()}",
                input_hash=str(new_count),
                result="{}",
                created_at=db.now(),
            )
            db.insert(
                conn,
                "runs",
                event_id=event_id,
                workflow_id=wid,
                agent="FormFlow",
                trigger="google_form_sync",
                tool="receive_registration",
                summary=summary,
                mode="Google Forms API",
                status="Completed",
                created_at=db.now(),
            )
            db.insert(
                conn,
                "activity",
                event_id=event_id,
                title=f"FormFlow synced {new_count} registration{'s' if new_count != 1 else ''}",
                description=summary,
                agent="FormFlow",
                created_at=db.now(),
            )

    logger.info("Synced %d new registrations for event %s", new_count, event_id)
    return new_count


def google_form_for_event(event_id: str) -> dict | None:
    """Return Google Form metadata for *event_id*, or ``None``."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM google_forms WHERE event_id=?", (event_id,),
        ).fetchone()
        if row is None:
            return None
        cnt_row = conn.execute(
            "SELECT COUNT(*) cnt FROM google_form_responses WHERE event_id=?",
            (event_id,),
        ).fetchone()
    record = dict(row)
    record["response_count"] = cnt_row["cnt"] if cnt_row else 0
    return record


def google_form_qr_svg(event_id: str) -> str | None:
    """Return an SVG string with a QR code pointing to the Google Form, or ``None``."""
    gf = google_form_for_event(event_id)
    if gf is None:
        return None

    from reportlab.graphics import renderSVG
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing

    widget = QrCodeWidget(gf["responder_uri"], barWidth=180, barHeight=180)
    drawing = Drawing(180, 180)
    drawing.add(widget)
    return renderSVG.drawToString(drawing)


def suggest_questions(event_name: str, event_type: str, description: str) -> list[dict]:
    """Use Gemini to suggest event-specific registration questions with sensible fallback."""
    default_questions = [
        {"title": "College / Department", "type": "text", "required": True, "options": []},
        {"title": "Team Name", "type": "text", "required": False, "options": []},
        {
            "title": "Track / Domain",
            "type": "dropdown",
            "required": True,
            "options": ["AI & Agents", "Web & Cloud", "Hardware & IoT", "Open Innovation"],
        },
        {"title": "GitHub / Portfolio Link", "type": "text", "required": False, "options": []},
        {
            "title": "T-Shirt Size",
            "type": "multiple_choice",
            "required": False,
            "options": ["S", "M", "L", "XL"],
        },
    ]
    try:
        from typing import Literal
        from pydantic import BaseModel, Field
        from . import intelligence

        class FormQuestion(BaseModel):
            title: str = Field(min_length=3, max_length=200)
            type: Literal["text", "paragraph", "multiple_choice", "dropdown"] = "text"
            required: bool = False
            options: list[str] = Field(default_factory=list, max_length=10)

        class FormQuestions(BaseModel):
            questions: list[FormQuestion] = Field(max_length=8)

        payload = {
            "event_name": event_name,
            "event_type": event_type,
            "description": description,
            "task": (
                "Suggest 4-6 short, practical registration questions specific to "
                "this event (e.g. College/Department, Team Name, Track/Domain, GitHub/Portfolio Link, T-Shirt Size). "
                "Do not include Full Name or Email — those are added automatically. "
                "For choice questions, provide 3-5 realistic options."
            ),
        }
        fallback = FormQuestions(questions=[FormQuestion(**q) for q in default_questions])
        result, _, _ = intelligence.structured("Relay", payload, FormQuestions, fallback)
        return [q.model_dump() for q in result.questions] or default_questions
    except Exception:
        logger.debug("Question suggestion unavailable — using default event questions")
        return default_questions


def poll_form_responses() -> int:
    """Sync responses for every event that has a linked Google Form and connected club."""
    total = 0
    with db.transaction() as conn:
        forms = conn.execute(
            """SELECT gf.event_id, gf.club_id
               FROM google_forms gf
               JOIN google_oauth_tokens tok ON tok.club_id = gf.club_id"""
        ).fetchall()

    for row in forms:
        try:
            total += sync_form_responses(row["club_id"], row["event_id"])
        except Exception:
            logger.debug("Skipped response sync for event %s", row["event_id"], exc_info=True)

    return total
