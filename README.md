# ClubOS

**Plan. Sponsor. Execute. Automate.**

ClubOS is a local event and sponsorship workspace for campus technical clubs. It implements the proposed interpretation of PS-CA2, Multi-Agent Technical Club Event & Sponsorship Lifecycle Orchestrator, for SYNCHRONISE 2026. Organizers can move from planning an event to reviewing sponsor terms, assigning deliverables and approving a recovery when funding or timelines change.

## Run ClubOS

From the repository root run:

```sh
./start.sh
```

Open **http://127.0.0.1:8017**. The first start seeds Nexus Technical Club, CodeStorm 2026, and Build Night 2026 in SQLite. The landing page opens first. Use **Try the demo** to explore CodeStorm, or create an account and enter your club name, institution and role to start an empty workspace. Each account sees its own club events. The launcher uses the built frontend and virtual environment when available. A clean machine needs uv with Python 3.12 and Node 22.12+ with pnpm or npm. Allow network access for dependency installation on first use.

For separate frontend development, run the API on port 8017 and run `pnpm dev` in `frontend`. Vite proxies API requests to the backend. To refresh the production UI, run `pnpm build` inside `frontend` before starting the server.

## Demo workspace

CodeStorm starts with INR 20,000 in club funds, INR 45,000 in confirmed sponsorships, INR 20,000 in sponsor payments received and INR 60,000 in planned costs. All partner identities and contacts in the sample are fictional. Dates are relative to first initialization so the demo has upcoming deadlines.

Use the withdrawal scenario to remove an unpaid INR 20,000 pledge. Ledger calculates the INR 15,000 shortfall. Sentinel flags the risk and Nexus coordinates proposed savings, backup outreach and assigned recovery work. Review or reject the proposal in Approvals. Approved prospective outreach still contributes zero to confirmed funding.

## Launch an event

1. Create an organizer account and save your club, college, and available club funds.
2. Select **New event**, fill in the quick basics, and type or dictate a single brief. **Try sample brief** fills in a hackathon example.
3. Watch Nexus interpret the brief, FormFlow publish the registration form, OpsLedger build the budget and milestone timeline, and Magnet draft partner pitches.
4. Use **Registrations & Form** to edit the form, copy its link, show the QR code, check in participants, or export a CSV. Public submissions update the organizer view live.
5. Use **Sponsorships** to review simulated outreach. Approve dispatch, simulate a reply, and review the simulated commitment. The workflow stores its activity and drafts locally.

Mission Control brings those outcomes together with pending approvals. **Plan & Budget** shows milestones, recorded expenses, and sponsor receivables. The CodeStorm demo also includes sponsor withdrawal and recovery scenarios.

The default registration links work on the computer running ClubOS. To demo across devices on a trusted local network, start ClubOS with `CLUBOS_HOST=0.0.0.0` and `CLUBOS_PUBLIC_URL=http://YOUR_LAN_IP:8017`. Both devices must be able to reach that address. Set an externally reachable HTTPS origin when using a reverse proxy.

## Optional Gemini

Copy `.env.example` to `.env` and set `GEMINI_API_KEY` to a key you control. Set `GEMINI_MODEL` to a GenerateContent-compatible model enabled for that key and restart the backend. The server uses Google's official Gen AI SDK, JSON schemas, timeouts, limited retries and validation. Selected event context and submitted sponsor text are sent to Gemini for relevant calls when configured. Secrets stay server-side. Without credentials the labelled deterministic mode supports the live demonstration.

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

For a rehearsal machine, copy the source, install the prerequisites, run the launcher and keep the process running. Persist `backend/data` across restarts or use `CLUBOS_DB` on a persistent volume. Keep the matching `<database filename>.trace.sqlite3` file on the same volume for execution history. This is a single-process, loopback organizer demo. Organizer accounts and workspace isolation are intended for local testing. Public deployment requires production authentication controls, account recovery, backups and a managed job runner. The prototype uses fictional prospect profiles, organizer-reviewed drafts and manually recorded financial facts. It does not send email, publish marketing, process payments or verify externally negotiated agreements. PDF extraction requires selectable text. Automation time-savings are estimates. Gmail, public registration, QR passes, certificates, real-time web prospect research and refund processing remain outside this local prototype.

See [architecture](docs/architecture.md), [API notes](docs/api.md), [demo walkthrough](docs/demo-guide.md) and the [development checklist](docs/checklist.md). Sample inputs are in [demo](demo/).
