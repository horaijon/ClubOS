# Runtime architecture

The React application and FastAPI API share a loopback origin. Event selection scopes all reads and commands. The REST snapshot combines the selected event, ledger, tasks, people, exposures and workflow history. The frontend refreshes the snapshot after successful mutations and on streamed commit events.

## Event processing

Nexus dispatches a typed event to specialist handlers. Atlas builds a dependency graph and deadlines. Ledger calculates cash and projected balances in integer paise. Magnet matches fictional sponsor profiles, drafts outreach and extracts terms. Echo prepares editable communications. Relay assigns event work and handles attendance. Sentinel applies domain rules to detect exposures.

The server controls every SQL mutation. Gemini can supply contextual explanations, editable copy and structured extraction through one server-side SDK adapter. Model outputs are schema-validated. Missing credentials, invalid responses and provider failures select the labelled fallback. A textual proposal has no authority to execute a budget or workflow change.

Organizer actions use an event-scoped idempotency key. The database transaction records the trigger, specialist runs, plan and action history. A recovery plan contains executable action records and the projected balance used when preparing financial changes. Decision handling checks the pending state before changing expenses, tasks or sponsor pipeline entries. Prospects remain outside the secured funding calculation.

## Storage and execution

SQLite uses foreign keys and explicit write transactions. Planning jobs expose persisted queued, running, completed and failed states. Each new execution writes a Nexus root and linked specialist runs to the SQLite journal beside the workspace database. The independent journal makes handoffs and tool calls visible over SSE while the workspace write transaction is open. The commit event follows the successful workspace commit, and a failed execution records a terminal failure. Historical seed runs carry their original fixture timestamps. The single-process reminder worker scans once per minute. The server stores structured records locally. Uploaded agreement PDFs are size-limited, parsed in a bounded subprocess, and returned as editable text. The upload route does not record a commitment. Reports read the same event snapshot as the dashboard. Projected funding uses club funds and confirmed commitments. Available cash uses club funds and recorded payments, less recorded expenses. Projected balance subtracts the greater of planned and incurred spending per category so overruns appear while the approved allocations remain visible.

For future PostgreSQL support, replace the database adapter and migrate the SQLite-specific SQL and transaction locking. The client interacts only with the versioned application source's REST contract. A shared deployment also needs identity, authorization and a durable job worker.
