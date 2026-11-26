"""FastAPI routes for real Gmail outreach/reply tracking and Google Forms sync."""
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from . import auth, db, forms_integration, gmail_integration, google_oauth
from .state import get_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["google-integrations"])


class SendEmailRequest(BaseModel):
    to_email: str = Field(min_length=3, max_length=254)
    subject: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=16000)


class FormQuestionInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: str = Field(default="text")
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=20)


class CreateGoogleFormRequest(BaseModel):
    questions: list[FormQuestionInput] | None = None


class BulkEmailItem(BaseModel):
    sponsor_id: str = Field(min_length=1, max_length=150)
    to_email: str = Field(min_length=3, max_length=254)
    subject: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=16000)


class BulkSendRequest(BaseModel):
    items: list[BulkEmailItem] = Field(min_length=1, max_length=50)
    simulate: bool = False


@router.post("/events/{event_id}/outreach-list/discover")
def discover_outreach_list_route(event_id: str, club: auth.Workspace):
    """Have Magnet gather real companies + contact emails and draft a specialized email for each."""
    from . import planning, sponsor_discovery, sponsorship, state

    with db.transaction(write=True) as c:
        auth.authorize_event(c, event_id, club["id"])
        event = get_event(c, event_id)
        wid = db.insert(
            c,
            "workflows",
            event_id=event_id,
            trigger="discover_outreach_list",
            request_id=f"discover:{db.uid()}",
            input_hash=event_id,
            result="{}",
            created_at=db.now(),
        )
        flow = planning.Flow(c, event, wid, "discover_outreach_list")

        # Discover real companies + websites + public contact emails
        sponsor_discovery.discover_and_upsert_real_sponsors(c, event, verify_websites=True)

        all_prospects = state.prospects(c, event, include_directory=True)
        pmap = {p["id"]: p for p in all_prospects}
        queue_rows = c.execute(
            """SELECT s.*, p.name, p.industry, p.description,
                      COALESCE(NULLIF(s.contact_email,''), p.contact_email, '') AS resolved_email,
                      COALESCE(p.website, '') AS website
               FROM sponsors s JOIN profiles p ON p.id=s.prospect_id
               WHERE s.event_id=? AND s.stage NOT IN ('Confirmed','Declined','Withdrawn')
               ORDER BY (COALESCE(NULLIF(s.contact_email,''), p.contact_email, '') != '') DESC, s.rowid DESC""",
            (event_id,),
        ).fetchall()

        items = []
        drafted_count = 0
        for row in queue_rows:
            s = dict(row)
            draft_text = (s.get("draft") or "").strip()
            if not draft_text:
                res = sponsorship.draft(flow, {"sponsor_id": s["id"]}, "outreach")
                draft_text = res["text"]
                drafted_count += 1
            subject, body = sponsorship.parse_email_subject_and_body(
                draft_text, event["name"], s["name"]
            )
            prof = pmap.get(s["prospect_id"], {})
            items.append({
                "sponsor_id": s["id"],
                "name": s["name"],
                "industry": s["industry"],
                "website": s.get("website", ""),
                "description": s.get("description", ""),
                "score": prof.get("score", 78),
                "reason": prof.get("reason", s.get("description", "")),
                "stage": s["stage"],
                "contact_email": (s.get("resolved_email") or "").strip(),
                "subject": subject,
                "body": body,
            })

        summary = f"Magnet discovered {len(items)} sponsor contacts with company profiles & emails ({drafted_count} newly drafted)."
        flow.log("Magnet", "rank_sponsors", summary)
        flow.note("Outreach list ready", summary, "Magnet")

    return {"items": items, "message": summary}


class AiKeysRequest(BaseModel):
    openai_api_key: str | None = Field(default=None, max_length=300)
    gemini_api_key: str | None = Field(default=None, max_length=300)
    cloudflare_account_id: str | None = Field(default=None, max_length=200)
    cloudflare_api_token: str | None = Field(default=None, max_length=300)


@router.get("/integrations/ai/status")
def ai_status_route(club: auth.Workspace):
    import os
    return {
        "openai_configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "cloudflare_configured": bool(
            os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
            and os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        ),
        "free_ai_available": True,
    }


@router.post("/integrations/ai/keys")
def save_ai_keys_route(data: AiKeysRequest, club: auth.Workspace):
    import os
    from pathlib import Path
    from . import intelligence

    if os.getenv("CLUBOS_PUBLIC_URL"):
        raise HTTPException(403, "On the hosted site, set AI keys in the hosting dashboard's environment settings.")

    env_path = Path(__file__).resolve().parents[2] / ".env"
    existing_lines = env_path.read_text().splitlines() if env_path.exists() else []
    updates = {}
    if data.openai_api_key is not None and data.openai_api_key.strip():
        val = data.openai_api_key.strip()
        os.environ["OPENAI_API_KEY"] = val
        updates["OPENAI_API_KEY"] = val
    if data.gemini_api_key is not None and data.gemini_api_key.strip():
        val = data.gemini_api_key.strip()
        os.environ["GEMINI_API_KEY"] = val
        updates["GEMINI_API_KEY"] = val
        intelligence._cached_client.cache_clear()
    if data.cloudflare_account_id is not None and data.cloudflare_account_id.strip():
        val = data.cloudflare_account_id.strip()
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = val
        updates["CLOUDFLARE_ACCOUNT_ID"] = val
    if data.cloudflare_api_token is not None and data.cloudflare_api_token.strip():
        val = data.cloudflare_api_token.strip()
        os.environ["CLOUDFLARE_API_TOKEN"] = val
        updates["CLOUDFLARE_API_TOKEN"] = val

    if updates and env_path.parent.exists():
        new_lines = []
        seen = set()
        for line in existing_lines:
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                seen.add(key)
            else:
                new_lines.append(line)
        for k, v in updates.items():
            if k not in seen:
                new_lines.append(f"{k}={v}")
        env_path.write_text("\n".join(new_lines) + "\n")

    return {
        "openai_configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "cloudflare_configured": bool(
            os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
            and os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        ),
        "free_ai_available": True,
        "message": "AI API keys saved.",
    }


@router.post("/events/{event_id}/outreach-list/send-all")
def send_all_outreach_route(event_id: str, data: BulkSendRequest, club: auth.Workspace):
    """Send specialized emails to all confirmed contacts in one click."""
    import re
    from datetime import date, timedelta

    with db.transaction() as c:
        auth.authorize_event(c, event_id, club["id"])
        event = get_event(c, event_id)

    connected = google_oauth.is_club_connected(club["id"])
    if not connected and not data.simulate:
        raise HTTPException(409, "Connect Google (Gmail & Forms) first, or choose simulated send.")

    sent = []
    failed = []

    for item in data.items:
        to_email = item.to_email.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", to_email):
            failed.append({"sponsor_id": item.sponsor_id, "error": f"Invalid email: {item.to_email}"})
            continue

        with db.transaction() as c:
            srow = c.execute(
                "SELECT s.id, s.follow_up_days, p.name FROM sponsors s JOIN profiles p ON p.id=s.prospect_id WHERE s.id=? AND s.event_id=?",
                (item.sponsor_id, event_id),
            ).fetchone()
        if not srow:
            failed.append({"sponsor_id": item.sponsor_id, "error": "Sponsor not found."})
            continue

        try:
            if connected:
                res = gmail_integration.send_sponsor_email(
                    club_id=club["id"],
                    event_id=event_id,
                    sponsor_id=item.sponsor_id,
                    to_email=to_email,
                    subject=item.subject,
                    body=item.body,
                )
                delivery = "gmail"
            else:
                res = {"message_id": f"sim-{db.uid()[:8]}", "thread_id": ""}
                delivery = "simulated"
        except Exception as exc:
            failed.append({"sponsor_id": item.sponsor_id, "name": srow["name"], "error": str(exc)})
            continue

        follow = (date.today() + timedelta(days=srow["follow_up_days"] or 5)).isoformat()
        full_text = f"Subject: {item.subject}\n\n{item.body}"
        with db.transaction(write=True) as c:
            c.execute(
                "UPDATE sponsors SET stage='Contacted', contact_email=?, draft=?, follow_up_date=? WHERE id=?",
                (to_email, full_text, follow, item.sponsor_id),
            )
            db.insert(
                c,
                "communications",
                event_id=event_id,
                sponsor_id=item.sponsor_id,
                kind="gmail_outreach" if delivery == "gmail" else "simulation_outreach",
                text=full_text,
                created_at=db.now(),
            )
        sent.append({"sponsor_id": item.sponsor_id, "name": srow["name"], "to_email": to_email, "delivery": delivery, **res})

    if sent:
        with db.transaction(write=True) as c:
            wid = db.insert(
                c,
                "workflows",
                event_id=event_id,
                trigger="bulk_outreach_sent",
                request_id=f"bulk-send:{db.uid()}",
                input_hash=str(len(sent)),
                result="{}",
                created_at=db.now(),
            )
            names = ", ".join(x["name"] for x in sent[:4]) + (f" +{len(sent)-4} more" if len(sent) > 4 else "")
            mode_label = "Gmail API" if connected else "Simulated"
            summary = f"Magnet sent {len(sent)} personalized sponsor email{'s' if len(sent) != 1 else ''} ({names}) via {'Gmail' if connected else 'simulation'}."
            db.insert(
                c,
                "runs",
                event_id=event_id,
                workflow_id=wid,
                agent="Magnet",
                trigger="bulk_outreach_sent",
                tool="send_email" if connected else "draft_outreach",
                summary=summary,
                mode=mode_label,
                status="Completed",
                created_at=db.now(),
            )
            db.insert(
                c,
                "activity",
                event_id=event_id,
                title=f"Sent {len(sent)} sponsor emails",
                description=summary,
                agent="Magnet",
                created_at=db.now(),
            )

    return {
        "sent_count": len(sent),
        "failed_count": len(failed),
        "sent": sent,
        "failed": failed,
        "message": f"Sent {len(sent)} email{'s' if len(sent) != 1 else ''} successfully" + (f" ({len(failed)} failed)" if failed else "."),
    }


@router.post("/events/{event_id}/sponsors/{sponsor_id}/send-email")
def send_email_route(event_id: str, sponsor_id: str, data: SendEmailRequest, club: auth.Workspace):
    with db.transaction() as c:
        auth.authorize_event(c, event_id, club["id"])
        sponsor = c.execute(
            "SELECT s.id, p.name FROM sponsors s JOIN profiles p ON p.id=s.prospect_id WHERE s.id=? AND s.event_id=?",
            (sponsor_id, event_id),
        ).fetchone()
        if not sponsor:
            raise HTTPException(404, "Sponsor not found in this event.")

    if not google_oauth.is_club_connected(club["id"]):
        raise HTTPException(409, "Connect Google (Gmail & Forms) first to send real emails.")

    try:
        res = gmail_integration.send_sponsor_email(
            club_id=club["id"],
            event_id=event_id,
            sponsor_id=sponsor_id,
            to_email=data.to_email,
            subject=data.subject,
            body=data.body,
        )
    except gmail_integration.GmailUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception("Gmail send failed")
        raise HTTPException(502, f"Gmail API error: {exc}") from exc

    with db.transaction(write=True) as c:
        c.execute(
            "UPDATE sponsors SET stage='Contacted', contact_email=?, draft=?, follow_up_date=NULL WHERE id=?",
            (data.to_email.strip().lower(), f"Subject: {data.subject}\n\n{data.body}", sponsor_id),
        )
        db.insert(
            c,
            "communications",
            event_id=event_id,
            sponsor_id=sponsor_id,
            kind="gmail_outreach",
            text=f"Subject: {data.subject}\n\n{data.body}",
            created_at=db.now(),
        )
        wid = db.insert(
            c,
            "workflows",
            event_id=event_id,
            trigger="send_real_email",
            request_id=f"gmail-send:{res['id']}",
            input_hash=res["id"],
            result="{}",
            created_at=db.now(),
        )
        summary = f"Magnet sent sponsorship pitch to {data.to_email.strip()} via Gmail."
        db.insert(
            c,
            "runs",
            event_id=event_id,
            workflow_id=wid,
            agent="Magnet",
            trigger="send_real_email",
            tool="send_email",
            summary=summary,
            mode="Gmail API",
            status="Completed",
            created_at=db.now(),
        )
        db.insert(
            c,
            "activity",
            event_id=event_id,
            title=f"Sent pitch to {sponsor['name']}",
            description=summary,
            agent="Magnet",
            created_at=db.now(),
        )

    return {"message": f"Email sent to {data.to_email.strip()}.", **res}


@router.post("/events/{event_id}/check-replies")
def check_replies_route(event_id: str, club: auth.Workspace):
    with db.transaction() as c:
        auth.authorize_event(c, event_id, club["id"])

    if not google_oauth.is_club_connected(club["id"]):
        raise HTTPException(409, "Connect Google (Gmail & Forms) first to check live Gmail replies.")

    replies = gmail_integration.check_replies(club["id"], event_id)
    return {
        "count": len(replies),
        "replies": replies,
        "message": f"Found {len(replies)} new sponsor {'reply' if len(replies) == 1 else 'replies'}." if replies else "Inbox checked — no new sponsor replies yet.",
    }


@router.get("/events/{event_id}/sponsors/{sponsor_id}/emails")
def sponsor_emails_route(event_id: str, sponsor_id: str, club: auth.Workspace):
    with db.transaction() as c:
        auth.authorize_event(c, event_id, club["id"])
        sponsor = c.execute(
            "SELECT 1 FROM sponsors WHERE id=? AND event_id=?", (sponsor_id, event_id)
        ).fetchone()
        if not sponsor:
            raise HTTPException(404, "Sponsor not found in this event.")
    return {"emails": gmail_integration.email_history(event_id, sponsor_id)}


@router.post("/events/{event_id}/create-google-form")
def create_google_form_route(
    event_id: str,
    club: auth.Workspace,
    data: CreateGoogleFormRequest | None = None,
):
    with db.transaction() as c:
        auth.authorize_event(c, event_id, club["id"])
        event = get_event(c, event_id)
        reg = c.execute(
            "SELECT deadline FROM registration_forms WHERE event_id=?", (event_id,)
        ).fetchone()
        deadline = (reg["deadline"] if reg else None) or event.get("milestone_date") or event["start_date"]

    if not google_oauth.is_club_connected(club["id"]):
        raise HTTPException(409, "Connect Google (Gmail & Forms) first to create a real Google Form.")

    questions: list[dict[str, Any]]
    if data and data.questions:
        questions = [q.model_dump() for q in data.questions]
    else:
        questions = forms_integration.suggest_questions(
            event["name"], event.get("type", "Event"), event.get("description") or event.get("goals", "")
        )

    try:
        res = forms_integration.create_google_form(
            club_id=club["id"],
            event_id=event_id,
            event_name=event["name"],
            event_data={**event, "deadline": deadline},
            questions=questions,
        )
    except Exception as exc:
        logger.exception("Failed to create Google Form")
        raise HTTPException(502, f"Google Forms API error: {exc}") from exc

    return {"message": "Google Form created and linked.", **res}


@router.post("/events/{event_id}/sync-form-responses")
def sync_form_responses_route(event_id: str, club: auth.Workspace):
    with db.transaction() as c:
        auth.authorize_event(c, event_id, club["id"])

    if not google_oauth.is_club_connected(club["id"]):
        raise HTTPException(409, "Connect Google (Gmail & Forms) first to sync form responses.")

    gf = forms_integration.google_form_for_event(event_id)
    if not gf:
        raise HTTPException(404, "Create a Google Form for this event first.")

    try:
        count = forms_integration.sync_form_responses(club["id"], event_id)
    except Exception as exc:
        logger.exception("Failed to sync Google Form responses")
        raise HTTPException(502, f"Google Forms sync error: {exc}") from exc

    return {
        "new_count": count,
        "message": f"Synced {count} new registration{'s' if count != 1 else ''} from Google Forms." if count else "Google Form is up to date — no new submissions yet.",
    }


@router.get("/events/{event_id}/google-form")
def get_google_form_route(event_id: str, club: auth.Workspace):
    with db.transaction() as c:
        auth.authorize_event(c, event_id, club["id"])
    gf = forms_integration.google_form_for_event(event_id)
    return {"google_form": gf}


@router.get("/events/{event_id}/google-form/qr.svg")
def google_form_qr_route(event_id: str, club: auth.Workspace):
    with db.transaction() as c:
        auth.authorize_event(c, event_id, club["id"])
    svg = forms_integration.google_form_qr_svg(event_id)
    if svg is None:
        raise HTTPException(404, "No Google Form found for this event.")
    return Response(svg, media_type="image/svg+xml")
