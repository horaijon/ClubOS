"""Real Gmail sending and reply tracking for the Magnet sponsorship agent.

Requires the sibling ``google_oauth`` module for authenticated Gmail API
access. When Google OAuth is not connected the caller falls back to the
existing simulation behaviour — this module raises ``GmailUnavailable``
to signal that case explicitly.
"""

import base64
import json
import logging
import re
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Literal

from pydantic import BaseModel, Field

from . import intelligence
from .db import encode, insert, now, rows, transaction, uid
from .recovery import currency
from .state import due_in

log = logging.getLogger(__name__)

GMAIL_SCHEMA = """
CREATE TABLE IF NOT EXISTS gmail_messages (
    id               TEXT PRIMARY KEY,
    event_id         TEXT NOT NULL,
    sponsor_id       TEXT NOT NULL,
    gmail_message_id TEXT,
    gmail_thread_id  TEXT,
    recipient_email  TEXT NOT NULL,
    subject          TEXT NOT NULL,
    body             TEXT NOT NULL,
    direction        TEXT NOT NULL CHECK(direction IN ('outbound','inbound')),
    parsed_status    TEXT,
    parsed_amount    INTEGER,
    sent_at          TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_gmail_messages_event ON gmail_messages(event_id);
CREATE INDEX IF NOT EXISTS ix_gmail_messages_sponsor ON gmail_messages(sponsor_id);
CREATE INDEX IF NOT EXISTS ix_gmail_messages_thread ON gmail_messages(gmail_thread_id);
"""


class GmailUnavailable(Exception):
    """Raised when Google OAuth is not connected for the given club."""


class ReplyClassification(BaseModel):
    status: Literal["replied_interested", "negotiating", "confirmed", "declined"] = "negotiating"
    amount_paise: int | None = Field(default=None, ge=0, le=10**13)
    deliverables: list[str] = Field(default_factory=list, max_length=12)
    summary: str = Field(min_length=1, max_length=600)
    follow_up_subject: str = Field(min_length=1, max_length=200)
    follow_up_body: str = Field(min_length=1, max_length=4000)


def _get_gmail_service(club_id: str):
    """Return an authenticated Gmail API resource, or raise ``GmailUnavailable``."""
    try:
        from .google_oauth import get_gmail_service
        service = get_gmail_service(club_id)
        if service is None:
            raise GmailUnavailable("Google account is not connected.")
        return service
    except ImportError:
        raise GmailUnavailable("google_oauth module is not available.")
    except Exception as exc:
        if isinstance(exc, GmailUnavailable):
            raise
        log.warning("Gmail service unavailable (%s): %s", type(exc).__name__, exc)
        raise GmailUnavailable(str(exc)) from exc


def _get_connected_email(club_id: str) -> str | None:
    """Return the Gmail address of the connected club account, or ``None``."""
    try:
        from .db import connect
        c = connect()
        try:
            row = c.execute(
                "SELECT email FROM google_oauth_tokens WHERE club_id=?",
                (club_id,),
            ).fetchone()
            return row["email"] if row else None
        finally:
            c.close()
    except Exception:
        return None


def _sanitize(text: str) -> str:
    """Strip HTML tags to prevent injection in outgoing plain-text email."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _build_mime(
    to: str,
    subject: str,
    body: str,
    from_email: str | None = None,
    thread_id: str | None = None,
) -> dict:
    """Build a base64url-encoded MIME payload for the Gmail API."""
    msg = MIMEText(_sanitize(body), "plain", "utf-8")
    msg["To"] = to
    msg["Subject"] = _sanitize(subject)
    if from_email:
        msg["From"] = from_email
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    payload: dict = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id
    return payload


def is_google_connected(club_id: str) -> bool:
    """Quick check for whether Gmail is usable for this club."""
    try:
        from .google_oauth import is_club_connected
        return is_club_connected(club_id)
    except Exception:
        return False


def send_sponsor_email(
    club_id: str,
    event_id: str,
    sponsor_id: str,
    to_email: str,
    subject: str,
    body: str,
    thread_id: str | None = None,
    conn=None,
) -> dict:
    """Send a real email via Gmail and persist the record."""
    to_email = to_email.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", to_email):
        raise ValueError("Provide a valid recipient email address.")

    service = _get_gmail_service(club_id)
    from_email = _get_connected_email(club_id)

    mime_payload = _build_mime(to_email, subject, body, from_email, thread_id=thread_id)
    result = (
        service.users()
        .messages()
        .send(userId="me", body=mime_payload)
        .execute()
    )

    gmail_message_id = result.get("id", "")
    gmail_thread_id = result.get("threadId", thread_id or "")
    sent_at = now()
    clean_subject = _sanitize(subject)
    clean_body = _sanitize(body)

    row_id = uid()

    def _persist(c):
        insert(
            c,
            "gmail_messages",
            id=row_id,
            event_id=event_id,
            sponsor_id=sponsor_id,
            gmail_message_id=gmail_message_id,
            gmail_thread_id=gmail_thread_id,
            recipient_email=to_email,
            subject=clean_subject,
            body=clean_body,
            direction="outbound",
            sent_at=sent_at,
            created_at=sent_at,
        )

    if conn is not None:
        _persist(conn)
    else:
        with transaction(write=True) as c:
            _persist(c)

    log.info("Sent Gmail message %s to %s (thread=%s)", gmail_message_id, to_email, gmail_thread_id)
    return {
        "id": row_id,
        "message_id": gmail_message_id,
        "thread_id": gmail_thread_id,
        "sent_at": sent_at,
    }


def _classify_reply(
    reply_text: str,
    sponsor_name: str,
    event_name: str,
    subject: str,
    thread_context: str = "",
) -> dict:
    """Use Gemini structured JSON output to classify a sponsor reply and draft a follow-up."""
    source = reply_text.strip()[:24000]
    terms = intelligence.extract_terms(source, "response")

    interest = terms.get("interest", "uncertain")
    if interest == "declined":
        fallback_status = "declined"
    elif re.search(r"\b(confirm|confirmed|locked|approved|deal|finalized)\b", source, re.I) and terms.get("amount"):
        fallback_status = "confirmed"
    elif interest == "interested":
        fallback_status = "replied_interested"
    else:
        fallback_status = "negotiating"

    amt = terms.get("amount")
    amt_str = currency(amt) if amt else "your proposed support"
    fallback_follow_up = (
        f"Hi {sponsor_name} team,\n\n"
        f"Thank you for getting back to us regarding {event_name}. "
        + (f"We are excited to move forward with {amt_str} and the requested deliverables. " if fallback_status != "declined" else "We completely understand and appreciate your time. ")
        + "Please let us know if you need our sponsorship deck or MoU details.\n\nBest regards,\nOrganizing Team"
    )
    fallback = ReplyClassification(
        status=fallback_status,
        amount_paise=amt,
        deliverables=terms.get("deliverables", []),
        summary=terms.get("summary", source[:280]) or f"Reply received from {sponsor_name}.",
        follow_up_subject=f"Re: {subject}" if not subject.lower().startswith("re:") else subject,
        follow_up_body=fallback_follow_up,
    )

    payload = {
        "sponsor": sponsor_name,
        "event": event_name,
        "subject": subject,
        "thread_context": thread_context[:4000],
        "reply_text": source,
        "task": (
            "Classify this sponsor's email reply as one of: replied_interested, negotiating, confirmed, declined. "
            "Extract any offered/committed INR amount in integer paise (1 rupee = 100 paise, so ₹25,000 = 2500000). "
            "Extract requested deliverables (booth, logo, shoutout, speaking slot, etc.). "
            "Write a concise 1-sentence summary and draft a polite, specific follow-up email reply."
        ),
    }
    parsed, mode, _ = intelligence.structured("Magnet", payload, ReplyClassification, fallback)
    data = parsed.model_dump()
    if data["amount_paise"] is None and amt is not None:
        data["amount_paise"] = amt
    if not data["deliverables"] and terms.get("deliverables"):
        data["deliverables"] = terms["deliverables"]
    data["mode"] = mode
    return {
        "status": data["status"],
        "amount": data["amount_paise"],
        "deliverables": data["deliverables"],
        "summary": data["summary"],
        "follow_up_subject": data["follow_up_subject"],
        "follow_up_body": data["follow_up_body"],
        "mode": mode,
    }


def _extract_body(payload: dict) -> str:
    """Recursively extract the first plain-text part from a Gmail payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                return ""
    if mime == "text/html" and not payload.get("parts"):
        data = payload.get("body", {}).get("data", "")
        if data:
            try:
                html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                return re.sub(r"<[^>]+>", " ", html).strip()
            except Exception:
                return ""
    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text
    return ""


def check_replies(club_id: str, event_id: str) -> list[dict]:
    """Check Gmail threads for new inbound replies for a given event."""
    try:
        service = _get_gmail_service(club_id)
    except GmailUnavailable:
        return []

    connected_email = (_get_connected_email(club_id) or "").lower()

    with transaction() as c:
        event_row = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not event_row:
            return []
        event = dict(event_row)
        outbound = rows(
            c,
            """SELECT DISTINCT gmail_thread_id, sponsor_id
               FROM gmail_messages
               WHERE event_id=? AND direction='outbound'
                 AND gmail_thread_id IS NOT NULL AND gmail_thread_id != ''""",
            (event_id,),
        )

    new_replies: list[dict] = []

    for record in outbound:
        thread_id = record["gmail_thread_id"]
        sponsor_id = record["sponsor_id"]

        try:
            thread = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
        except Exception:
            log.warning("Failed to fetch thread %s", thread_id)
            continue

        messages = thread.get("messages", [])

        with transaction() as c:
            known_ids = {
                r["gmail_message_id"]
                for r in c.execute(
                    "SELECT gmail_message_id FROM gmail_messages WHERE gmail_thread_id=?",
                    (thread_id,),
                )
            }
            sponsor_row = c.execute(
                """SELECT s.*, p.name FROM sponsors s
                   JOIN profiles p ON p.id = s.prospect_id
                   WHERE s.id=?""",
                (sponsor_id,),
            ).fetchone()
            if not sponsor_row:
                continue
            sponsor = dict(sponsor_row)

        thread_context = "\n---\n".join(
            _extract_body(m.get("payload", {}))[:800] for m in messages[:-1]
        )

        for msg in messages:
            msg_id = msg.get("id", "")
            if not msg_id or msg_id in known_ids:
                continue

            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            sender = headers.get("from", "")
            if connected_email and connected_email in sender.lower():
                continue
            if "SENT" in msg.get("labelIds", []) and not (sponsor.get("contact_email") and sponsor["contact_email"].lower() in sender.lower()):
                continue

            body_text = _extract_body(msg.get("payload", {}))
            if not body_text:
                continue

            subject = headers.get("subject", "(no subject)")
            internal_date = msg.get("internalDate")
            sent_at = (
                datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).isoformat(
                    timespec="milliseconds"
                )
                if internal_date
                else now()
            )

            classification = _classify_reply(
                body_text,
                sponsor["name"],
                event["name"],
                subject,
                thread_context,
            )

            row_id = uid()
            with transaction(write=True) as c:
                # Re-fetch sponsor inside write txn to avoid race conditions
                s_curr = c.execute("SELECT * FROM sponsors WHERE id=?", (sponsor_id,)).fetchone()
                if not s_curr:
                    continue
                s_curr = dict(s_curr)

                insert(
                    c,
                    "gmail_messages",
                    id=row_id,
                    event_id=event_id,
                    sponsor_id=sponsor_id,
                    gmail_message_id=msg_id,
                    gmail_thread_id=thread_id,
                    recipient_email=sender,
                    subject=_sanitize(subject),
                    body=_sanitize(body_text[:16000]),
                    direction="inbound",
                    parsed_status=classification["status"],
                    parsed_amount=classification["amount"],
                    sent_at=sent_at,
                    created_at=now(),
                )

                # Update sponsor stage
                next_stage = s_curr["stage"]
                if s_curr["stage"] != "Confirmed":
                    next_stage = "Declined" if classification["status"] == "declined" else "Responded"
                    c.execute(
                        "UPDATE sponsors SET stage=?, follow_up_date=NULL WHERE id=?",
                        (next_stage, sponsor_id),
                    )

                insert(
                    c,
                    "communications",
                    event_id=event_id,
                    sponsor_id=sponsor_id,
                    kind="response",
                    text=_sanitize(body_text[:16000]),
                    terms=encode({
                        "interest": "declined" if classification["status"] == "declined" else "interested",
                        "amount": classification["amount"],
                        "deliverables": classification["deliverables"],
                        "summary": classification["summary"],
                        "mode": classification["mode"],
                    }),
                    created_at=now(),
                )

                # Create workflow + run + activity + approval card
                wid = insert(
                    c,
                    "workflows",
                    event_id=event_id,
                    trigger="gmail_reply_received",
                    request_id=f"gmail-reply:{msg_id}",
                    input_hash=msg_id,
                    result="{}",
                    created_at=now(),
                )
                amt = classification.get("amount")
                amt_label = f" ({currency(amt)})" if amt else ""
                summary_msg = f"Magnet received real reply from {sponsor['name']}{amt_label}: {classification['summary']}"

                insert(
                    c,
                    "runs",
                    event_id=event_id,
                    workflow_id=wid,
                    agent="Magnet",
                    trigger="gmail_reply_received",
                    tool="extract_terms",
                    summary=summary_msg,
                    mode=classification["mode"],
                    status="Completed",
                    created_at=now(),
                )
                insert(
                    c,
                    "activity",
                    event_id=event_id,
                    title=f"Magnet received reply from {sponsor['name']}",
                    description=summary_msg,
                    agent="Magnet",
                    created_at=now(),
                )

                actions = []
                if classification["status"] != "declined":
                    if amt and s_curr["stage"] != "Confirmed":
                        actions.append({
                            "type": "confirm",
                            "title": f"Confirm {currency(amt)} from {sponsor['name']}",
                            "sponsor_id": sponsor_id,
                            "amount": amt,
                            "due_date": event["start_date"],
                            "before_stage": next_stage,
                            "before_amount": s_curr["committed"],
                        })
                        for title in dict.fromkeys(classification["deliverables"]):
                            if re.search(r"payment|instalment|installment", title, re.I) and not re.search(r"booth|speak|brand|logo", title, re.I):
                                continue
                            dept = "Operations" if re.search(r"booth|speak|slot|stall|room|equipment", title, re.I) else "Marketing"
                            actions.append({
                                "type": "deliverable",
                                "title": title[:500],
                                "department": dept,
                                "sponsor_id": sponsor_id,
                                "due_date": event["start_date"],
                            })
                    elif s_curr["stage"] not in ("Confirmed", "Negotiating"):
                        actions.append({
                            "type": "negotiate",
                            "title": f"Move {sponsor['name']} to Negotiating",
                            "sponsor_id": sponsor_id,
                            "before_stage": next_stage,
                            "before_amount": s_curr["committed"],
                        })

                    recipient = s_curr.get("contact_email") or sender
                    if recipient:
                        actions.append({
                            "type": "send_reply_email",
                            "title": f"Send Magnet's drafted reply to {sponsor['name']}",
                            "sponsor_id": sponsor_id,
                            "to_email": recipient,
                            "subject": classification["follow_up_subject"],
                            "body": classification["follow_up_body"],
                            "thread_id": thread_id,
                        })

                if actions:
                    approval_title = (
                        f"Confirm {currency(amt)} from {sponsor['name']} & send reply?"
                        if amt and s_curr["stage"] != "Confirmed"
                        else f"Send Magnet's drafted reply to {sponsor['name']}?"
                    )
                    insert(
                        c,
                        "approvals",
                        event_id=event_id,
                        workflow_id=wid,
                        title=approval_title,
                        description=classification["summary"],
                        actions=encode(actions),
                        created_at=now(),
                    )

            new_replies.append(
                {
                    "id": row_id,
                    "sponsor_id": sponsor_id,
                    "sponsor_name": sponsor["name"],
                    "thread_id": thread_id,
                    "gmail_message_id": msg_id,
                    "sender": sender,
                    "subject": subject,
                    "body_preview": body_text[:500],
                    **classification,
                }
            )

    return new_replies


def email_history(event_id: str, sponsor_id: str) -> list[dict]:
    """Return the full email exchange for a sponsor, ordered chronologically."""
    with transaction() as c:
        return rows(
            c,
            """SELECT id, gmail_message_id, gmail_thread_id, recipient_email,
                      subject, body, direction, parsed_status, parsed_amount,
                      sent_at, created_at
               FROM gmail_messages
               WHERE event_id=? AND sponsor_id=?
               ORDER BY sent_at ASC, rowid ASC""",
            (event_id, sponsor_id),
        )


def poll_gmail_replies() -> int:
    """Check replies for all events whose clubs have Google connected."""
    from .db import connect
    c = connect()
    try:
        pairs = [
            dict(r)
            for r in c.execute(
                """SELECT DISTINCT e.club_id, gm.event_id
                   FROM gmail_messages gm
                   JOIN events e ON e.id = gm.event_id
                   JOIN google_oauth_tokens tok ON tok.club_id = e.club_id
                   WHERE gm.direction='outbound'
                     AND gm.gmail_thread_id IS NOT NULL
                     AND gm.gmail_thread_id != ''"""
            )
        ]
    finally:
        c.close()

    total_new = 0
    for pair in pairs:
        try:
            new_replies = check_replies(pair["club_id"], pair["event_id"])
            total_new += len(new_replies)
        except Exception:
            log.exception("Reply poll failed for event %s", pair["event_id"])

    if total_new:
        log.info("Gmail poller found %d new replies.", total_new)
    return total_new
