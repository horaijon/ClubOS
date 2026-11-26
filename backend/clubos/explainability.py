"""Decision explainability (rules, constraints, scores) and timestamped appeal audit trail."""
from datetime import date
import json
import re

from . import db
from .recovery import currency
from .state import (
    Conflict,
    Invalid,
    Missing,
    budgets,
    choice,
    funding,
    get_event,
    prospects,
    required,
    scoped,
    task_rows,
)

TARGET_TYPES = ("approval", "risk", "disruption", "sponsor", "run", "poster")
APPEAL_STATES = ("Flagged", "Under Review", "Overridden", "Dismissed")


def _load_target_record(c, event_id: str, target_type: str, target_id: str) -> dict:
    if target_type == "sponsor":
        row = c.execute(
            """SELECT s.*, p.name, p.industry, p.description, p.tags, p.relationship, p.sponsorship_type
               FROM sponsors s JOIN profiles p ON p.id=s.prospect_id
               WHERE s.id=? AND s.event_id=?""",
            (target_id, event_id),
        ).fetchone()
        if row:
            return dict(row)
        e = get_event(c, event_id)
        match = next(
            (p for p in prospects(c, e, include_directory=True) if p["id"] == target_id),
            None,
        )
        if match:
            return {"is_prospect": True, **match}
        raise Missing("Sponsor or prospect record not found in this event.")

    table = {
        "approval": "approvals",
        "risk": "risks",
        "disruption": "disruptions",
        "run": "runs",
        "poster": "posters",
    }[target_type]
    return scoped(c, table, target_id, event_id)


def explain(c, event_id: str, target_type: str, target_id: str) -> dict:
    target_type = choice(target_type, TARGET_TYPES, "decision target")
    event = get_event(c, event_id)
    record = _load_target_record(c, event_id, target_type, target_id)

    rules: list[dict] = []
    constraints: list[dict] = []
    scores: list[dict] = []
    inputs: dict = {}
    agent = "Nexus"
    mode = "Deterministic"
    title = ""
    summary = ""
    created_at = record.get("created_at") or event.get("created_at") or db.now()
    outcome_status = record.get("status") or "Recorded"

    if target_type == "approval":
        actions = json.loads(record["actions"]) if isinstance(record["actions"], str) else record["actions"]
        title = record["title"]
        summary = record.get("description") or ""
        outcome_status = record["status"]
        runs = db.rows(
            c, "SELECT agent, mode, tool, summary FROM runs WHERE workflow_id=? ORDER BY rowid", (record["workflow_id"],)
        )
        if runs:
            agent = runs[-1]["agent"]
            mode = runs[-1]["mode"]
        money = funding(c, event)
        inputs = {
            "approval_status": record["status"],
            "action_count": len(actions),
            "basis_balance": currency(record["basis_balance"]) if record.get("basis_balance") is not None else None,
            "current_balance": currency(money["balance"]),
        }
        constraints.append({
            "label": "Human approval gate",
            "limit": "Organizer confirmation required before mutating workspace records",
            "actual": record["status"],
        })
        if record.get("basis_balance") is not None:
            constraints.append({
                "label": "Financial consistency lock",
                "limit": f"Projected balance must remain {currency(record['basis_balance'])}",
                "actual": currency(money["balance"]),
            })
        for act in actions:
            atype = act.get("type", "")
            if atype in ("reduce_budget", "reallocate_budget"):
                amt = act.get("saving") or act.get("amount") or 0
                rules.append({
                    "name": "Adjustable unspent budget rule",
                    "condition": "saving <= min(remaining_gap, category.adjustable, category.planned - category.actual)",
                    "result": act.get("title", f"Adjust {currency(amt)}"),
                    "passed": True,
                })
            elif atype == "move_deadline":
                rules.append({
                    "name": "DAG schedule & event window rule",
                    "condition": f"proposed_date = min(event.end_date ({event['end_date']}), due_date + delay)",
                    "result": act.get("title", "Shift task deadline"),
                    "passed": True,
                })
            elif atype == "backup_outreach":
                rules.append({
                    "name": "Backup partner selection rule",
                    "condition": "Select top 2 ranked prospects in stage None | Shortlisted | Identified",
                    "result": act.get("title", "Draft backup outreach"),
                    "passed": True,
                })
            elif atype in ("confirm", "negotiate", "deliverable", "send_reply_email"):
                rules.append({
                    "name": "Term extraction & stage transition rule",
                    "condition": "Extracted offer amount/deliverables queued for organizer verification",
                    "result": act.get("title", atype),
                    "passed": True,
                })
            elif atype == "campaign":
                rules.append({
                    "name": "Registration shortfall threshold",
                    "condition": f"registered < registration_milestone ({event['registration_milestone']})",
                    "result": act.get("title", "Launch campaign"),
                    "passed": True,
                })
            else:
                rules.append({
                    "name": "Workflow action rule",
                    "condition": f"Validated action type '{atype}'",
                    "result": act.get("title", atype),
                    "passed": True,
                })
        scores.append({
            "metric": "Net budget impact",
            "value": currency(sum(a.get("saving", 0) for a in actions)),
            "weight_or_basis": "Sum of proposed cost reductions",
        })

    elif target_type == "risk":
        agent = (json.loads(record["agents"]) if isinstance(record["agents"], str) else record["agents"] or ["Sentinel"])[0]
        title = record["title"]
        summary = record.get("description") or ""
        outcome_status = f"{record['severity']} · {record['status']}"
        fp = record.get("fingerprint") or ""
        money = funding(c, event)
        reg_count = c.execute("SELECT COUNT(*) FROM participants WHERE event_id=?", (event_id,)).fetchone()[0]
        inputs = {"fingerprint": fp, "severity": record["severity"], "source": record["source"]}
        if fp == "funding-gap":
            rules.append({
                "name": "Funding shortfall threshold",
                "condition": "exposure > projected_funding (initial_budget + confirmed_sponsorships)",
                "result": f"Shortfall {currency(money['shortfall'])}",
                "passed": money["shortfall"] > 0,
            })
            constraints.append({
                "label": "Coverage ratio",
                "limit": currency(money["exposure"]),
                "actual": currency(money["projected_funding"]),
            })
        elif fp.startswith("registration:"):
            rules.append({
                "name": "Registration checkpoint rule",
                "condition": f"registered < registration_milestone ({event['registration_milestone']}) on/after {event['milestone_date']}",
                "result": f"{reg_count} / {event['registration_milestone']} registered",
                "passed": True,
            })
        elif fp.startswith("overdue:"):
            rules.append({
                "name": "Task overdue threshold",
                "condition": "task.due_date < today AND task.status != 'Completed'",
                "result": f"Severity assigned: {record['severity']}",
                "passed": True,
            })
        elif fp.startswith("deliverable:"):
            rules.append({
                "name": "Confirmed deliverable proximity rule",
                "condition": "Confirmed sponsor deliverable due within 3 days (High if past due)",
                "result": record.get("impact") or "Flagged for owner review",
                "passed": True,
            })
        elif fp.startswith("payment:"):
            rules.append({
                "name": "Sponsor receivable collection rule",
                "condition": "confirmed_amount - received_payments > 0 within 10 days of due/start date",
                "result": record.get("impact") or "Payment reminder triggered",
                "passed": True,
            })
        else:
            rules.append({
                "name": "Automated Sentinel detection",
                "condition": record.get("source") or "Event state scan",
                "result": record.get("impact") or record["severity"],
                "passed": True,
            })
        scores.append({
            "metric": "Risk severity",
            "value": record["severity"],
            "weight_or_basis": "Computed from priority/deadline/shortfall thresholds",
        })

    elif target_type == "disruption":
        agent = "Nexus"
        mode = "Chaos Re-Router"
        title = record["title"]
        summary = record.get("summary") or ""
        changes = json.loads(record.get("changes") or "[]")
        actions_taken = json.loads(record.get("actions_taken") or "[]")
        notifications = json.loads(record.get("notifications") or "[]")
        kind = record.get("kind") or "venue"
        outcome_status = f"{len(changes)} change(s) applied"
        inputs = {"disruption_kind": kind, "affected_records": len(changes), "notifications": len(notifications)}
        rule_map = {
            "venue": ("Venue relocation rule", "Mutate events.venue + public registration page + notify participants & confirmed sponsors"),
            "asset": ("Topological DAG cascade rule", f"Shift selected task and dependent unfinished tasks, capped at end_date ({event['end_date']})"),
            "cutoff": ("Eligibility & deadline gate", f"Enforce deadline <= start_date ({event['start_date']}); sync registration milestone & notify"),
            "cancellation": ("Cancellation impact rule", "Block cancelled task / close form if event-wide + log Sentinel risk + notify stakeholders"),
        }
        rname, rcond = rule_map.get(kind, ("Disruption rule", "Targeted record recomputation"))
        rules.append({"name": rname, "condition": rcond, "result": f"{len(changes)} record(s) recomputed", "passed": True})
        if notifications:
            real_count = sum(1 for n in notifications if n.get("status") != "simulated")
            rules.append({
                "name": "Stakeholder email safety & dispatch rule",
                "condition": "Send Gmail only to non-synthetic domains; simulate *.test/*.example demo addresses",
                "result": f"{real_count} real recipient(s), {len(notifications) - real_count} simulated",
                "passed": True,
            })
        for act_line in actions_taken:
            constraints.append({"label": "Executed action", "limit": "Targeted impact only", "actual": act_line})
        scores.append({
            "metric": "Blast radius",
            "value": f"{len(changes)} records",
            "weight_or_basis": "Scoped exclusively to impacted entities",
        })

    elif target_type == "sponsor":
        agent = "Magnet"
        mode = "Sponsor Ranking Engine"
        title = record["name"]
        summary = record.get("description") or ""
        outcome_status = record.get("stage") or "Prospect"
        words = set(
            re.findall(
                r"[a-z0-9]+",
                " ".join(str(event[k]).lower() for k in ("type", "name", "goals", "description", "college", "venue")).replace("hackathons", "hackathon"),
            )
        )
        raw_tags = record.get("tags") or ""
        tags = raw_tags.split(",") if isinstance(raw_tags, str) else list(raw_tags)
        if not raw_tags:
            match = next((p for p in prospects(c, event, include_directory=True) if p["id"] == record.get("prospect_id")), None)
            score_val = match["score"] if match else 65
            matched = []
        else:
            matched = [t for t in tags if t and t in words]
            rel_bonus = 6 if record.get("relationship") else 0
            student_bonus = 4 if "student" in tags else 0
            tag_pts = min(3, len(matched)) * 11
            score_val = min(99, 55 + tag_pts + rel_bonus + student_bonus)
            rules.append({
                "name": "Keyword tag alignment",
                "condition": "55 base + 11 pts per matching event/tag keyword (max 3)",
                "result": f"+{tag_pts} pts ({', '.join(matched) if matched else 'no exact tag hits'})",
                "passed": len(matched) > 0,
            })
            rules.append({
                "name": "Relationship & campus affinity bonus",
                "condition": "+6 prior club relationship; +4 student-focused tag",
                "result": f"+{rel_bonus + student_bonus} pts",
                "passed": (rel_bonus + student_bonus) > 0,
            })
        tier = (
            "In-Kind Partner"
            if (record.get("sponsorship_type") or "").replace("-", " ").lower() == "in kind"
            else "Gold Sponsor" if score_val >= 70 else "Silver Sponsor"
        )
        rules.append({
            "name": "Automated package tier assignment",
            "condition": "In-Kind if service/hardware; Gold if score >= 70; else Silver",
            "result": f"Recommended tier: {tier}",
            "passed": True,
        })
        scores.append({
            "metric": "Match score",
            "value": f"{score_val} / 99",
            "weight_or_basis": "Weighted tag overlap + prior relationship + student affinity",
        })
        constraints.append({
            "label": "Email verification constraint",
            "limit": "Real Gmail requires a saved contact_email",
            "actual": record.get("contact_email") or "Not set",
        })
        inputs = {"industry": record.get("industry"), "sponsorship_type": record.get("sponsorship_type"), "score": score_val}

    elif target_type == "run":
        agent = record["agent"]
        mode = record["mode"]
        title = f"{record['agent']} · {record['tool']}"
        summary = record["summary"]
        outcome_status = record["status"]
        inputs = {"trigger": record["trigger"], "tool": record["tool"], "mode": record["mode"]}
        rules.append({
            "name": "Agent tool authorization",
            "condition": f"Tool '{record['tool']}' belongs to {record['agent']}'s allow-listed capability set",
            "result": "Authorized & logged",
            "passed": True,
        })
        constraints.append({
            "label": "Execution mode",
            "limit": "Bounded single-transaction state mutation",
            "actual": record["mode"],
        })

    else:  # poster
        agent = "Canvas"
        mode = record.get("theme") or "Canvas"
        title = record["title"]
        summary = record.get("prompt") or "Event poster generated from saved event brief and metadata."
        outcome_status = "Active" if record.get("is_active") else record.get("kind", "draft")
        inputs = {"kind": record["kind"], "mime_type": record["mime_type"], "prompt": record.get("prompt")}
        rules.append({
            "name": "Poster provider cascade",
            "condition": "OpenAI -> Gemini -> Cloudflare Workers AI -> Free FLUX.1-schnell -> Vector SVG",
            "result": f"Selected: {record.get('theme')}",
            "passed": True,
        })
        constraints.append({
            "label": "Verified metadata integrity",
            "limit": "Dates, venue, and registration QR code overlaid programmatically for free raster posters",
            "actual": f"{event['start_date']} · {event['venue']}",
        })

    appeals = db.rows(
        c,
        """SELECT * FROM decision_appeals
           WHERE event_id=? AND target_type=? AND target_id=?
           ORDER BY rowid DESC""",
        (event_id, target_type, target_id),
    )
    persisted_logs = db.rows(
        c,
        """SELECT * FROM decision_audit_logs
           WHERE event_id=? AND target_type=? AND target_id=?
           ORDER BY created_at ASC, rowid ASC""",
        (event_id, target_type, target_id),
    )
    audit_log = [
        {
            "id": f"origin-{target_type}-{target_id}",
            "appeal_id": None,
            "actor": agent,
            "from_status": "",
            "to_status": "Automated Outcome Created",
            "note": summary or title,
            "created_at": created_at,
        },
        *persisted_logs,
    ]

    return {
        "target_type": target_type,
        "target_id": target_id,
        "title": title,
        "agent": agent,
        "mode": mode,
        "outcome_status": outcome_status,
        "summary": summary,
        "rules": rules,
        "constraints": constraints,
        "scores": scores,
        "inputs": inputs,
        "appeals": appeals,
        "audit_log": audit_log,
    }


def submit_appeal(flow, p: dict) -> dict:
    c = flow.c
    target_type = choice(p.get("target_type"), TARGET_TYPES, "decision target")
    target_id = required(p, "target_id", 150)
    reason = required(p, "reason", 1000)
    override_request = (p.get("override_request") or "").strip()[:1000]
    actor = (p.get("actor") or "Organizer").strip()[:120] or "Organizer"

    info = explain(c, flow.id, target_type, target_id)
    now_ts = db.now()
    appeal_id = db.insert(
        c,
        "decision_appeals",
        event_id=flow.id,
        target_type=target_type,
        target_id=target_id,
        title=info["title"][:240],
        reason=reason,
        override_request=override_request,
        status="Flagged",
        resolution_note="",
        submitted_by=actor,
        created_at=now_ts,
        updated_at=now_ts,
    )
    audit_note = reason + (f" | Requested override: {override_request}" if override_request else "")
    db.insert(
        c,
        "decision_audit_logs",
        event_id=flow.id,
        appeal_id=appeal_id,
        target_type=target_type,
        target_id=target_id,
        actor=actor,
        from_status="Automated Outcome",
        to_status="Flagged",
        note=audit_note[:1200],
        created_at=now_ts,
    )
    with flow.tool("Nexus", "record_appeal", {"target_type": target_type, "target_id": target_id}) as step:
        step.update(
            summary=f"Flagged {target_type} decision '{info['title'][:60]}' for review.",
            output={"appeal_id": appeal_id, "status": "Flagged"},
        )
    flow.note(f"Decision flagged: {info['title'][:60]}", reason[:160])
    return dict(
        message="Decision flagged and logged to the audit trail.",
        appeal_id=appeal_id,
        status="Flagged",
    )


def transition_appeal(flow, p: dict) -> dict:
    c = flow.c
    appeal = scoped(c, "decision_appeals", p.get("appeal_id"), flow.id)
    next_status = choice(p.get("status"), APPEAL_STATES, "appeal status")
    note = (p.get("resolution_note") or "").strip()[:1000]
    actor = (p.get("actor") or "Organizer").strip()[:120] or "Organizer"

    if next_status == appeal["status"] and not note:
        raise Invalid("Choose a new status or enter a resolution note.")

    now_ts = db.now()
    c.execute(
        "UPDATE decision_appeals SET status=?, resolution_note=?, updated_at=? WHERE id=?",
        (next_status, note or appeal.get("resolution_note", ""), now_ts, appeal["id"]),
    )
    db.insert(
        c,
        "decision_audit_logs",
        event_id=flow.id,
        appeal_id=appeal["id"],
        target_type=appeal["target_type"],
        target_id=appeal["target_id"],
        actor=actor,
        from_status=appeal["status"],
        to_status=next_status,
        note=note or f"Status transitioned from {appeal['status']} to {next_status}.",
        created_at=now_ts,
    )

    if next_status == "Overridden" and p.get("apply_override"):
        if appeal["target_type"] == "risk":
            c.execute("UPDATE risks SET status='Closed' WHERE id=? AND event_id=?", (appeal["target_id"], flow.id))
        elif appeal["target_type"] == "approval":
            c.execute(
                "UPDATE approvals SET status='Rejected', decided_at=? WHERE id=? AND event_id=? AND status='Pending'",
                (now_ts, appeal["target_id"], flow.id),
            )

    with flow.tool("Nexus", "record_appeal", {"appeal_id": appeal["id"], "status": next_status}) as step:
        step.update(
            summary=f"Appeal '{appeal['title'][:50]}' transitioned {appeal['status']} -> {next_status}.",
            output={"appeal_id": appeal["id"], "from": appeal["status"], "to": next_status},
        )
    flow.note(f"Appeal {next_status.lower()}: {appeal['title'][:50]}", note or f"Updated from {appeal['status']}.")
    return dict(
        message=f"Appeal status updated to {next_status}.",
        appeal_id=appeal["id"],
        status=next_status,
    )
