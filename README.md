# ClubOS

**Plan. Sponsor. Execute. Automate.**

ClubOS is a local event and sponsorship workspace for campus technical clubs. It implements the proposed interpretation of PS-CA2, Multi-Agent Technical Club Event & Sponsorship Lifecycle Orchestrator, for SYNCHRONISE 2026. Organizers can move from planning an event to reviewing sponsor terms, assigning deliverables and approving a recovery when funding or timelines change.

## What's inside

| Page | What you can do |
|---|---|
| **Mission Control** | See registrations, sponsorships, budget, agent activity and pending approvals, and trigger a campus disruption (venue, asset, cutoff or cancellation) with before/after changes and stakeholder alerts. |
| **AI Copilot** | Ask questions about the event, request actions, and review outgoing email before it is sent. |
| **Registrations & Form** | Publish a local form or a Google Form, sync responses (including Track / Domain), check in participants and export CSV. |
| **Poster Studio** | Generate posters from a prompt, upload a style reference or a final poster, and manage versions. |
| **Sponsorships** | Discover contacts, edit drafted emails, send to one company or to all, and check Gmail replies. |
| **Plan & Budget** | Track milestones, record, edit and delete expenses, and follow the funding breakdown. |

Agent decisions can be inspected with **Why decided?** and disputed with **Appeal**.

## Run ClubOS

From the repository root run:

```sh
./start.sh
```

Open **http://127.0.0.1:8018**. The first start seeds Nexus Technical Club, CodeStorm 2026, and Build Night 2026 in SQLite. The landing page opens first. Use **Try the demo** to explore CodeStorm, or create an account and enter your club name, institution and role to start an empty workspace. Each account sees its own club events. The launcher uses the built frontend and virtual environment when available. A clean machine needs uv with Python 3.12 and Node 22.12+ with pnpm or npm. Allow network access for dependency installation on first use.

For separate frontend development, run the API on port 8018 and run `pnpm dev` in `frontend`. Vite proxies API requests to the backend. To refresh the production UI, run `pnpm build` inside `frontend` before starting the server.

## Demo workspace

CodeStorm starts with INR 20,000 in club funds, INR 45,000 in confirmed sponsorships, INR 20,000 in sponsor payments received and INR 60,000 in planned costs. All partner identities and contacts in the sample are fictional. Dates are relative to first initialization so the demo has upcoming deadlines.

Use the withdrawal scenario to remove an unpaid INR 20,000 pledge. Ledger calculates the INR 15,000 shortfall. Sentinel flags the risk and Nexus coordinates proposed savings, backup outreach and assigned recovery work. Review or reject the proposal in Approvals. Approved prospective outreach still contributes zero to confirmed funding.

## Launch an event

1. Create an organizer account (or use **Continue with Google**) and save your club, college, and available club funds.
2. Select **New event**, fill in the quick basics, and type or dictate a single brief, including team size, tracks and prizes. **Try sample brief** fills in a hackathon example.
3. Watch Nexus interpret the brief, FormFlow publish the registration form, OpsLedger build the budget and milestone timeline, and Magnet draft partner pitches.
4. Use **Registrations & Form** to edit the form, copy its link, show the QR code, check in participants, or export a CSV.
5. Use **Sponsorships** to review outreach. With Google connected, emails go through your Gmail account. Without it, sends are simulated and labelled as such.

Mission Control brings those outcomes together with pending approvals. **Plan & Budget** shows milestones, recorded expenses, and sponsor receivables. The CodeStorm demo also includes sponsor withdrawal and recovery scenarios.

The default registration links work on the computer running ClubOS. To demo across devices on a trusted local network, start ClubOS with `CLUBOS_HOST=0.0.0.0` and `CLUBOS_PUBLIC_URL=http://YOUR_LAN_IP:8018`. Both devices must be able to reach that address. Set an externally reachable HTTPS origin when using a reverse proxy.

## Configuration

Copy `.env.example` to `.env`, fill in only what you need, and restart ClubOS. Never commit `.env`.

### Google sign-in, Gmail and Forms

1. In Google Cloud Console, enable the **Gmail API** and **Google Forms API**.
2. Create an OAuth client of type **Web application** with the redirect URI `http://127.0.0.1:8018/api/integrations/google/callback`.
3. While the app is in testing, add your Google account as a test user.
4. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REDIRECT_URI` in `.env`, and open ClubOS at the same address as the redirect URI.

**Continue with Google** signs you in and connects Gmail and Forms in one step. If you already have a password account, log in with your password and connect Google from the top bar once (disconnect first if it already shows connected) before using the button.

Connected accounts send real email: sponsor outreach, approved Copilot messages and disruption alerts. Check recipients before sending.

### AI providers

| Variable | Used for |
|---|---|
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Briefs, agent advice and poster design |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional OpenAI features |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | Poster artwork through Workers AI |
| `CLUBOS_LOCAL_COPILOT_MODEL`, `CLUBOS_LOCAL_COPILOT_PORT` | A local OpenAI-compatible model for Copilot (default port 8031) |

Without keys, ClubOS falls back to labelled deterministic agents. Poster Studio can also call free public image services. Event context, prompts and submitted sponsor text are sent to whichever external provider handles a request. Secrets stay server-side.

## Engineering and verification

React, TypeScript, Vite, Lucide and Recharts power the frontend. FastAPI, Pydantic and Python's SQLite adapter serve event-scoped commands. ReportLab generates PDFs and pypdf reads text-based agreements. Open **/docs** on the local server for the API explorer.

```sh
.venv/bin/python -m pytest -q
cd frontend
pnpm build
pnpm exec playwright install chromium
pnpm test:e2e
```

Browser tests start an isolated server on port 8028 and use a temporary database. The browser configuration also accepts `CHROMIUM_PATH` and detects Brave on macOS. Set `CLUBOS_DB` to select a different database and `PORT` to change the launch port. To initialize a separate clean demo, set `CLUBOS_DB` to a new file path and start the app.

## Deployment and scope

For a rehearsal machine, copy the source, install the prerequisites, run the launcher and keep the process running. Persist `backend/data` across restarts or use `CLUBOS_DB` on a persistent volume. Keep the matching `<database filename>.trace.sqlite3` file on the same volume for execution history. This is a single-process, loopback organizer demo. Organizer accounts and workspace isolation are intended for local testing. Public deployment requires production authentication controls, account recovery, backups and a managed job runner. The seeded demo uses fictional prospect profiles and manually recorded financial facts. Verify discovered sponsor contacts before emailing them. ClubOS does not publish marketing, process payments or verify externally negotiated agreements. PDF extraction requires selectable text. Automation time-savings are estimates.

See [architecture](docs/architecture.md), [API notes](docs/api.md), [demo walkthrough](docs/demo-guide.md) and the [development checklist](docs/checklist.md). Sample inputs are in [demo](demo/).
