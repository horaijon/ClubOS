# Local API

Visit /docs on the running server for interactive OpenAPI documentation.

| Route | Purpose |
| --- | --- |
| GET /api/events | List workspace events |
| POST /api/events | Create an event and synchronously run planning |
| POST /api/planning-jobs | Queue the event wizard's planning transaction |
| GET /api/jobs/{job_id} | Poll the durable job record |
| GET /api/events/{event_id} | Retrieve the event workspace and derived metrics |
| POST /api/events/{event_id}/actions | Dispatch a validated event command with type, payload and request_id |
| POST /api/events/{event_id}/agreement-text | Extract selectable text from a PDF submitted in multipart field file |
| GET /api/events/{event_id}/report.pdf | Download an event report |
| GET /api/events/{event_id}/sponsors/{sponsor_id}/report.pdf | Download an event-scoped partner report |
| GET /api/health | Check service readiness and key configuration |

All monetary API fields use integer paise. INR 25,000 is 2500000 paise. Dates use YYYY-MM-DD. Reuse the same request_id when retrying the same action. Errors return a detail field. Event creation and approval decisions must be performed through these routes to preserve workflow history.
