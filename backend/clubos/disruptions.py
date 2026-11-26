"""Event-scoped disruption recomputation, automatic stakeholder emails, and alerts."""
from datetime import date, timedelta
import json
import logging

from . import db, gmail_integration
from .state import Conflict, Invalid, choice, iso, number, required, scoped, task_rows

log = logging.getLogger(__name__)

_SYNTHETIC_TLDS = (".test", ".example", ".invalid", ".localhost")


def _is_synthetic_email(email: str) -> bool:
    low = (email or "").strip().lower()
    return not low or low.endswith(_SYNTHETIC_TLDS)


def _decode_json_list(raw) -> list:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except Exception:
        return []


def history(c, eid):
    out = []
    for row in db.rows(
        c, "SELECT * FROM disruptions WHERE event_id=? ORDER BY rowid DESC LIMIT 30", (eid,)
    ):
        item = dict(row)
        item["kind"] = item.get("kind") or "venue"
        item["summary"] = item.get("summary") or ""
        item["changes"] = _decode_json_list(item.get("changes"))
        item["actions_taken"] = _decode_json_list(item.get("actions_taken"))
        item["notifications"] = _decode_json_list(item.get("notifications"))
        out.append(item)
    return out


def _participants_for_event(c, event_id: str) -> list[dict]:
    return db.rows(
        c,
        "SELECT id, name, email FROM participants WHERE event_id=? AND email IS NOT NULL AND email != '' ORDER BY rowid",
        (event_id,),
    )


def _confirmed_sponsors_for_event(c, event_id: str) -> list[dict]:
    return db.rows(
        c,
        """SELECT s.id, p.name, COALESCE(NULLIF(s.contact_email,''), p.contact_email, '') AS email
           FROM sponsors s JOIN profiles p ON p.id=s.prospect_id
           WHERE s.event_id=? AND s.stage='Confirmed'
           ORDER BY s.committed DESC""",
        (event_id,),
    )


def _dispatch_notifications(club_id: str, queue: list[dict]) -> list[dict]:
    """Send real Gmail notices to valid recipients when connected; simulate demo addresses."""
    if not queue:
        return []
    connected = gmail_integration.is_google_connected(club_id)
    results: list[dict] = []
    seen_emails: set[str] = set()

    for item in queue:
        email = (item.get("email") or "").strip().lower()
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)
        entry = {
            "recipient_name": item.get("name") or "Participant",
            "recipient_email": email,
            "role": item.get("role") or "Participant",
            "subject": item["subject"],
            "body": item["body"],
            "status": "queued",
            "channel": "Pending Gmail",
            "message_id": "",
            "detail": "",
        }
        if _is_synthetic_email(email):
            entry["status"] = "simulated"
            entry["channel"] = "Simulation"
            entry["detail"] = "Demo/test address simulated locally (not emailed)."
        elif connected:
            try:
                sent = gmail_integration.send_notification_email(
                    club_id=club_id,
                    to_email=email,
                    subject=item["subject"],
                    body=item["body"],
                )
                entry["status"] = "sent"
                entry["channel"] = "Gmail"
                entry["message_id"] = sent.get("message_id", "")
                entry["detail"] = "Delivered via Gmail"
            except Exception as exc:
                log.warning("Disruption email to %s failed: %s", email, exc)
                entry["status"] = "failed"
                entry["channel"] = "Gmail"
                entry["detail"] = str(exc)[:180]
        else:
            entry["detail"] = "Connect Gmail to dispatch real emails."
        results.append(entry)

    return results


def _notification_summary(notifications: list[dict]) -> str:
    if not notifications:
        return ""
    sent = sum(1 for n in notifications if n["status"] == "sent")
    queued = sum(1 for n in notifications if n["status"] == "queued")
    sim = sum(1 for n in notifications if n["status"] == "simulated")
    failed = sum(1 for n in notifications if n["status"] == "failed")
    parts = []
    if sent:
        parts.append(f"{sent} sent via Gmail")
    if queued:
        parts.append(f"{queued} queued for Gmail")
    if sim:
        parts.append(f"{sim} demo simulated")
    if failed:
        parts.append(f"{failed} failed")
    return ", ".join(parts)


def _try_update_google_form_description(c, club_id: str, event: dict, note: str) -> bool:
    """Best-effort update of Google Form description when Google Forms is connected."""
    try:
        gf = c.execute(
            "SELECT google_form_id FROM google_forms WHERE event_id=? AND club_id=?",
            (event["id"], club_id),
        ).fetchone()
        if not gf:
            return False
        from . import forms_integration, google_oauth

        if not google_oauth.is_club_connected(club_id):
            return False
        service = forms_integration._get_forms_service(club_id)
        desc = forms_integration._build_description(event)
        if note:
            desc = f"[IMPORTANT UPDATE] {note}\n\n{desc}"
        service.forms().batchUpdate(
            formId=gf["google_form_id"],
            body={
                "requests": [
                    {
                        "updateFormInfo": {
                            "info": {"description": desc[:4000]},
                            "updateMask": "description",
                        }
                    }
                ]
            },
        ).execute()
        return True
    except Exception:
        log.debug("Skipped live Google Form description update", exc_info=True)
        return False


def trigger(flow, p):
    c, event = flow.c, flow.e
    kind = choice(p.get("kind"), ("venue", "asset", "cutoff", "cancellation"), "disruption")
    reason = (p.get("reason") or "").strip()[:400]
    notify_participants = bool(p.get("notify_participants", True))

    changes: list[dict] = []
    actions_taken: list[str] = []
    email_queue: list[dict] = []

    def change(record, field, before, after, audience):
        if before != after:
            changes.append(
                dict(record=record, field=field, before=before, after=after, audience=audience)
            )

    if kind == "venue":
        venue = required(p, "venue", 220)
        old_venue = event["venue"]
        change(
            event["name"],
            "Venue",
            old_venue,
            venue,
            "Registered participants, event staff, and confirmed sponsors",
        )
        if changes:
            c.execute("UPDATE events SET venue=? WHERE id=?", (venue, flow.id))
            actions_taken.append(f"Updated venue to {venue} & refreshed public registration page")
            updated_event = {**event, "venue": venue}
            if _try_update_google_form_description(
                c, event["club_id"], updated_event, f"Venue changed from {old_venue} to {venue}."
            ):
                actions_taken.append("Updated live Google Form description with new venue")

            if notify_participants:
                reason_line = f"\nReason: {reason}" if reason else ""
                for pt in _participants_for_event(c, flow.id):
                    email_queue.append(
                        {
                            "name": pt["name"],
                            "email": pt["email"],
                            "role": "Participant",
                            "subject": f"[Venue Change] {event['name']} moved to {venue}",
                            "body": (
                                f"Hi {pt['name']},\n\n"
                                f"Please note a venue update for {event['name']} ({event['start_date']}):\n\n"
                                f"• Previous venue: {old_venue}\n"
                                f"• New venue: {venue}{reason_line}\n\n"
                                f"Your registration remains confirmed. Please arrive at the updated venue.\n\n"
                                f"Best regards,\n{event['club']} Organizing Team"
                            ),
                        }
                    )
                for sp in _confirmed_sponsors_for_event(c, flow.id):
                    if sp["email"]:
                        email_queue.append(
                            {
                                "name": sp["name"],
                                "email": sp["email"],
                                "role": "Confirmed Sponsor",
                                "subject": f"[Partner Update] New venue for {event['name']}: {venue}",
                                "body": (
                                    f"Hello {sp['name']} team,\n\n"
                                    f"We are writing to inform you of a venue update for {event['name']} ({event['start_date']}):\n\n"
                                    f"• Previous venue: {old_venue}\n"
                                    f"• Updated venue: {venue}{reason_line}\n\n"
                                    f"All partner booth and branding placements are being relocated to {venue}.\n\n"
                                    f"Best regards,\n{event['club']}"
                                ),
                            }
                        )

    elif kind == "cutoff":
        from .registration import form_for_event, publish

        form = form_for_event(c, flow.id)
        eligibility_note = (p.get("eligibility_note") or "").strip()[:400]
        raw_target = p.get("target")
        raw_deadline = (p.get("deadline") or "").strip()

        if not raw_deadline and not eligibility_note and raw_target is None:
            raise Invalid("Provide a new deadline, eligibility cutoff note, or capacity cutoff.")

        new_cutoff = None
        if raw_deadline:
            if not form or not form.get("slug"):
                raise Conflict("Publish a ClubOS registration form before changing the cutoff.")
            if form.get("google_form_id") and not eligibility_note and raw_target is None:
                raise Conflict(
                    "This event uses Google Forms. Update the external form before rerouting its cutoff."
                )
            new_cutoff = iso(raw_deadline).isoformat()
            if new_cutoff > event["start_date"]:
                raise Invalid("Registration must close by the event start date.")
            if form.get("slug") and not form.get("google_form_id"):
                old_deadline = form["deadline"]
                change(
                    "Public registration form",
                    "Registration cutoff",
                    old_deadline,
                    new_cutoff,
                    "Registration team and prospective participants",
                )
                if new_cutoff != old_deadline:
                    publish(c, flow.id, new_cutoff, [field["key"] for field in form["fields"]])
                    c.execute(
                        "UPDATE events SET milestone_date=? WHERE id=? AND milestone_date=?",
                        (new_cutoff, flow.id, old_deadline),
                    )
                    for table in ("tasks", "milestones"):
                        c.execute(
                            f"UPDATE {table} SET due_date=? WHERE event_id=? AND title='Close registrations and confirm roster' AND due_date=?",
                            (new_cutoff, flow.id, old_deadline),
                        )
                    actions_taken.append(
                        f"Updated registration cutoff from {old_deadline} to {new_cutoff}"
                    )

        if eligibility_note:
            old_req = (event.get("requirements") or "").strip() or "Open to eligible campus students"
            change(
                event["name"],
                "Eligibility cutoff",
                old_req,
                eligibility_note,
                "Registered and prospective participants",
            )
            if eligibility_note != old_req:
                c.execute(
                    "UPDATE events SET requirements=? WHERE id=?", (eligibility_note, flow.id)
                )
                actions_taken.append("Updated participant eligibility criteria")

        if raw_target is not None and str(raw_target).strip() != "":
            cap = number(int(raw_target), "Capacity cutoff", 1, 100000)
            if cap != event["target"]:
                change(
                    event["name"],
                    "Capacity cutoff",
                    f"{event['target']} participants",
                    f"{cap} participants",
                    "Registration & operations team",
                )
                c.execute(
                    "UPDATE events SET target=?, registration_milestone=? WHERE id=?",
                    (cap, min(cap, max(1, cap // 2)), flow.id),
                )
                actions_taken.append(f"Adjusted participant capacity cap to {cap}")

        if changes and notify_participants:
            diff_lines = "\n".join(
                f"• {ch['field']}: {ch['before']} → {ch['after']}" for ch in changes
            )
            reason_line = f"\nNotes: {reason}" if reason else ""
            for pt in _participants_for_event(c, flow.id):
                email_queue.append(
                    {
                        "name": pt["name"],
                        "email": pt["email"],
                        "role": "Participant",
                        "subject": f"[Registration Update] Updated cutoff & eligibility for {event['name']}",
                        "body": (
                            f"Hi {pt['name']},\n\n"
                            f"Please review the updated registration cutoff details for {event['name']}:\n\n"
                            f"{diff_lines}{reason_line}\n\n"
                            f"Event dates: {event['start_date']} at {event['venue']}.\n\n"
                            f"Best regards,\n{event['club']}"
                        ),
                    }
                )

    elif kind == "cancellation":
        scope = choice(p.get("scope") or "session", ("session", "event"), "cancellation scope")
        if scope == "session":
            cancelled_task_id = (p.get("task_id") or "").strip()
            cancelled_track = (p.get("track") or "").strip()[:120]
            if not cancelled_task_id and not cancelled_track:
                raise Invalid("Select a task/session to cancel or specify a cancelled track.")

            if cancelled_task_id:
                task_row = scoped(c, "tasks", cancelled_task_id, flow.id)
                if task_row["status"] == "Completed":
                    raise Conflict("Cannot cancel an already completed task.")
                old_status = task_row["status"]
                change(
                    task_row["title"],
                    "Session / task status",
                    old_status,
                    "Cancelled (Blocked)",
                    f"{task_row['department']} lead and affected participants",
                )
                note_suffix = f"\n[Cancelled]: {reason or 'Cancelled via Campus Chaos Re-Router.'}"
                new_desc = (task_row.get("description") or "") + note_suffix
                c.execute(
                    "UPDATE tasks SET status='Blocked', description=? WHERE id=?",
                    (new_desc[:4000], task_row["id"]),
                )
                actions_taken.append(f"Marked '{task_row['title']}' as Cancelled (Blocked)")

            if cancelled_track:
                brief_row = c.execute(
                    "SELECT details FROM event_briefs WHERE event_id=?", (flow.id,)
                ).fetchone()
                if brief_row:
                    details = json.loads(brief_row["details"])
                    tracks = details.get("tracks") or []
                    remaining = [t for t in tracks if t.lower() != cancelled_track.lower()]
                    if len(remaining) != len(tracks):
                        details["tracks"] = remaining
                        c.execute(
                            "UPDATE event_briefs SET details=? WHERE event_id=?",
                            (db.encode(details), flow.id),
                        )
                        change(
                            "Event tracks",
                            "Cancelled track",
                            ", ".join(tracks),
                            ", ".join(remaining) or "All remaining tracks",
                            "Registered participants",
                        )
                        actions_taken.append(f"Removed cancelled track '{cancelled_track}' from brief & registration form")
                if not changes:
                    change(
                        cancelled_track,
                        "Session status",
                        "Scheduled",
                        "Cancelled",
                        "Registered participants & event operations",
                    )
                    actions_taken.append(f"Recorded cancellation of '{cancelled_track}'")

            flow.risk(
                f"cancel:{cancelled_task_id or cancelled_track}",
                f"Cancelled: {cancelled_track or task_row['title']}",
                reason or "Last-minute session/track cancellation triggered.",
                "High",
                "Participants and schedule may require immediate communication.",
                "Verify substitute activity and send schedule updates to attendees.",
                ["Sentinel", "Relay"],
            )
            actions_taken.append("Logged high-severity Sentinel risk for schedule review")

            if notify_participants and changes:
                item_label = cancelled_track or task_row["title"]
                reason_line = f"\nReason: {reason}" if reason else ""
                for pt in _participants_for_event(c, flow.id):
                    email_queue.append(
                        {
                            "name": pt["name"],
                            "email": pt["email"],
                            "role": "Participant",
                            "subject": f"[Schedule Change] Update for {event['name']}: {item_label}",
                            "body": (
                                f"Hi {pt['name']},\n\n"
                                f"Due to a last-minute campus update, the following change applies to {event['name']}:\n\n"
                                f"• Affected session/track: {item_label}\n"
                                f"• Status: Cancelled / Replaced{reason_line}\n\n"
                                f"All other sessions at {event['venue']} remain on schedule.\n\n"
                                f"Best regards,\n{event['club']}"
                            ),
                        }
                    )

        else:
            # Full event cancellation / postponement
            old_desc = event["description"]
            prefix = "[CANCELLED / POSTPONED] "
            new_desc = old_desc if old_desc.startswith(prefix) else prefix + old_desc
            change(
                event["name"],
                "Event status",
                "Active",
                "Cancelled / Postponed",
                "All registered participants, sponsors, and staff",
            )
            c.execute("UPDATE events SET description=? WHERE id=?", (new_desc[:3500], flow.id))
            actions_taken.append("Marked event description as Cancelled / Postponed")

            from .registration import form_for_event, publish

            form = form_for_event(c, flow.id)
            if form and form.get("slug") and not form.get("google_form_id"):
                closed_day = (date.today() - timedelta(days=1)).isoformat()
                if form["deadline"] >= date.today().isoformat():
                    change(
                        "Public registration form",
                        "Registration status",
                        f"Open until {form['deadline']}",
                        f"Closed ({closed_day})",
                        "Prospective participants",
                    )
                    publish(c, flow.id, closed_day, [field["key"] for field in form["fields"]])
                    actions_taken.append("Closed public registration form immediately")

            flow.risk(
                "event-cancelled",
                f"{event['name']} cancelled or postponed",
                reason or "Full event disruption triggered via Campus Chaos Re-Router.",
                "High",
                "All participants and sponsors must be notified; sponsor deliverables paused.",
                "Coordinate refunds/rescheduling with confirmed sponsors and venue team.",
                ["Sentinel", "Magnet", "Relay"],
            )
            actions_taken.append("Raised critical Sentinel risk & stakeholder alert")

            if notify_participants:
                reason_line = f"\nReason: {reason}" if reason else ""
                for pt in _participants_for_event(c, flow.id):
                    email_queue.append(
                        {
                            "name": pt["name"],
                            "email": pt["email"],
                            "role": "Participant",
                            "subject": f"[Important Notice] {event['name']} Cancelled / Postponed",
                            "body": (
                                f"Hi {pt['name']},\n\n"
                                f"We regret to inform you that {event['name']} (scheduled for {event['start_date']} at {event['venue']}) has been cancelled/postponed due to unforeseen campus circumstances.{reason_line}\n\n"
                                f"We will share rescheduled dates as soon as confirmed.\n\n"
                                f"Sincerely,\n{event['club']}"
                            ),
                        }
                    )
                for sp in _confirmed_sponsors_for_event(c, flow.id):
                    if sp["email"]:
                        email_queue.append(
                            {
                                "name": sp["name"],
                                "email": sp["email"],
                                "role": "Confirmed Sponsor",
                                "subject": f"[Urgent Partner Notice] {event['name']} Cancelled / Postponed",
                                "body": (
                                    f"Hello {sp['name']} team,\n\n"
                                    f"Please note that {event['name']} ({event['start_date']}) has been cancelled/postponed.{reason_line}\n\n"
                                    f"Our sponsorship lead will reach out shortly regarding rescheduled dates or settlement options.\n\n"
                                    f"Regards,\n{event['club']}"
                                ),
                            }
                        )

    else:
        # kind == 'asset'
        root = scoped(c, "tasks", p.get("task_id"), flow.id)
        if root["status"] == "Completed":
            raise Conflict("Choose an open task affected by the unavailable asset.")
        days = number(p.get("days"), "Delay", 1, 30)
        asset_name = (p.get("asset_name") or "").strip()[:120]
        tasks = {task["id"]: task for task in task_rows(c, flow.id)}
        dates = {key: task["due_date"] for key, task in tasks.items()}
        dates[root["id"]] = (iso(root["due_date"]) + timedelta(days=days)).isoformat()
        waiting = set(tasks)
        while waiting:
            ready = {key for key in waiting if not waiting.intersection(tasks[key]["dependencies"])}
            if not ready:
                raise Conflict("Task dependencies must be acyclic.")
            for key in sorted(ready):
                task = tasks[key]
                parents = [
                    parent
                    for parent in task["dependencies"]
                    if dates[parent] != tasks[parent]["due_date"]
                ]
                if parents:
                    dates[key] = max(dates[key], *(dates[parent] for parent in parents))
                if dates[key] != task["due_date"]:
                    if task["status"] == "Completed" or dates[key] > event["end_date"]:
                        raise Conflict(
                            f'{task["title"]} cannot move within the event window. Choose a smaller delay or a replacement asset.'
                        )
                    change(
                        task["title"],
                        "Due date",
                        task["due_date"],
                        dates[key],
                        task["owner"] or task["department"] + " team",
                    )
            waiting -= ready

        shifted_ids = [key for key, day in dates.items() if day != tasks[key]["due_date"]]
        for key in shifted_ids:
            day = dates[key]
            c.execute("UPDATE tasks SET due_date=? WHERE id=?", (day, key))
            milestone = c.execute(
                "SELECT id FROM milestones WHERE event_id=? AND title=? AND due_date=?",
                (flow.id, tasks[key]["title"], tasks[key]["due_date"]),
            ).fetchone()
            if milestone:
                c.execute("UPDATE milestones SET due_date=? WHERE id=?", (day, milestone["id"]))
                change(
                    tasks[key]["title"] + " milestone",
                    "Due date",
                    tasks[key]["due_date"],
                    day,
                    "Event planning team",
                )

        if shifted_ids:
            actions_taken.append(
                f"Recomputed dependency schedule for {len(shifted_ids)} affected task(s)"
                + (f" ({asset_name})" if asset_name else "")
            )
            placeholders = ",".join("?" for _ in shifted_ids)
            sponsor_links = db.rows(
                c,
                f"""SELECT d.task_id, p.name AS sponsor_name,
                           COALESCE(NULLIF(s.contact_email,''), p.contact_email, '') AS email
                    FROM deliverables d
                    JOIN sponsors s ON s.id=d.sponsor_id
                    JOIN profiles p ON p.id=s.prospect_id
                    WHERE d.event_id=? AND s.stage='Confirmed' AND d.task_id IN ({placeholders})""",
                (flow.id, *shifted_ids),
            )
            for link in sponsor_links:
                t_info = tasks[link["task_id"]]
                new_day = dates[link["task_id"]]
                if link["email"] and notify_participants:
                    email_queue.append(
                        {
                            "name": link["sponsor_name"],
                            "email": link["email"],
                            "role": "Confirmed Sponsor",
                            "subject": f"[Deliverable Update] {event['name']} — {t_info['title']}",
                            "body": (
                                f"Hello {link['sponsor_name']} team,\n\n"
                                f"Due to an equipment/asset delay{f' ({asset_name})' if asset_name else ''}, the preparation deadline for '{t_info['title']}' has shifted:\n\n"
                                f"• Previous date: {t_info['due_date']}\n"
                                f"• Revised date: {new_day}\n\n"
                                f"Your event-day branding and deliverables for {event['name']} remain on track.\n\n"
                                f"Best regards,\n{event['club']}"
                            ),
                        }
                    )
            if sponsor_links:
                actions_taken.append(
                    f"Flagged {len(sponsor_links)} sponsor deliverable(s) impacted by asset delay"
                )

    if not changes:
        raise Conflict("The disruption did not change any records.")

    notifications = _dispatch_notifications(event["club_id"], email_queue)
    notif_summary = _notification_summary(notifications)
    if notif_summary:
        actions_taken.append(f"Stakeholder emails: {notif_summary}")
        with flow.tool("Relay", "notify_stakeholders", {"disruption": kind, "recipients": len(notifications)}) as step:
            step.update(summary=f"Dispatched {len(notifications)} stakeholder alert(s): {notif_summary}.")

    title_map = {
        "venue": "Venue rerouted",
        "asset": "Asset delay rerouted",
        "cutoff": "Registration cutoff changed",
        "cancellation": "Cancellation rerouted",
    }
    title = title_map[kind]
    summary_text = reason or f"{len(changes)} affected records updated."

    key = db.insert(
        c,
        "disruptions",
        event_id=flow.id,
        title=title,
        kind=kind,
        summary=summary_text,
        changes=db.encode(changes),
        actions_taken=db.encode(actions_taken),
        notifications=db.encode(notifications),
        created_at=db.now(),
    )
    with flow.tool("Nexus", "apply_plan", {"disruption": kind}) as step:
        step.update(
            summary=f"{title}. {len(changes)} affected records updated."
            + (f" ({notif_summary})" if notif_summary else ""),
            output={"disruption_id": key, "changes": changes, "actions_taken": actions_taken},
        )
    flow.note(
        title,
        f"{len(changes)} targeted alerts"
        + (f" · {notif_summary}" if notif_summary else " in Mission Control."),
    )
    return dict(
        message=f"{title}. {len(changes)} affected records updated."
        + (f" Emails: {notif_summary}." if notif_summary else ""),
        disruption_id=key,
        actions_taken=actions_taken,
        notifications=notifications,
    )


def retry_notifications(flow, p):
    """Send any queued/failed disruption emails now that Gmail is connected."""
    c, event = flow.c, flow.e
    row = scoped(c, "disruptions", p.get("disruption_id"), flow.id)
    if not gmail_integration.is_google_connected(event["club_id"]):
        raise Conflict("Connect Gmail in the workspace header before sending queued emails.")

    existing = _decode_json_list(row.get("notifications"))
    pending = [n for n in existing if n.get("status") in ("queued", "failed") and not _is_synthetic_email(n.get("recipient_email", ""))]
    if not pending:
        return dict(message="No pending real participant emails to send.", sent=0)

    sent_count = 0
    failed_count = 0
    for item in existing:
        if item.get("status") in ("queued", "failed") and not _is_synthetic_email(item.get("recipient_email", "")):
            try:
                res = gmail_integration.send_notification_email(
                    club_id=event["club_id"],
                    to_email=item["recipient_email"],
                    subject=item["subject"],
                    body=item["body"],
                )
                item["status"] = "sent"
                item["channel"] = "Gmail"
                item["message_id"] = res.get("message_id", "")
                item["detail"] = "Delivered via Gmail"
                sent_count += 1
            except Exception as exc:
                item["status"] = "failed"
                item["detail"] = str(exc)[:180]
                failed_count += 1

    actions = _decode_json_list(row.get("actions_taken"))
    notif_summary = _notification_summary(existing)
    actions = [a for a in actions if not a.startswith("Stakeholder emails:")]
    if notif_summary:
        actions.append(f"Stakeholder emails: {notif_summary}")

    c.execute(
        "UPDATE disruptions SET notifications=?, actions_taken=? WHERE id=?",
        (db.encode(existing), db.encode(actions), row["id"]),
    )
    with flow.tool("Relay", "notify_stakeholders", {"disruption_id": row["id"], "sent": sent_count}) as step:
        step.update(summary=f"Sent {sent_count} queued disruption alert email(s) via Gmail.")
    flow.note("Disruption emails sent", f"Sent {sent_count} queued alert(s) via Gmail.", "Relay")
    return dict(
        message=f"Sent {sent_count} queued email(s) via Gmail."
        + (f" {failed_count} failed." if failed_count else ""),
        sent=sent_count,
        failed=failed_count,
    )
