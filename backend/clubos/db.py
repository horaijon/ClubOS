"""SQLite storage for the local demo club. Writers use explicit immediate transactions."""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clubs (id TEXT PRIMARY KEY, name TEXT NOT NULL, college TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT COLLATE NOCASE NOT NULL UNIQUE,
    salt TEXT NOT NULL, digest TEXT NOT NULL, club_id TEXT REFERENCES clubs
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, account_id TEXT REFERENCES accounts ON DELETE CASCADE, demo INTEGER NOT NULL DEFAULT 0,
    expires_at INTEGER NOT NULL,
    CHECK ((demo=1 AND account_id IS NULL) OR (demo=0 AND account_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS members (id TEXT PRIMARY KEY, club_id TEXT REFERENCES clubs(id), name TEXT NOT NULL, role TEXT NOT NULL, department TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, club_id TEXT NOT NULL REFERENCES clubs(id), name TEXT NOT NULL, type TEXT NOT NULL, description TEXT NOT NULL, venue TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, target INTEGER NOT NULL CHECK(target>0), initial_budget INTEGER NOT NULL CHECK(initial_budget>=0), sponsorship_target INTEGER NOT NULL CHECK(sponsorship_target>=0), college TEXT NOT NULL, goals TEXT NOT NULL, requirements TEXT NOT NULL, constraints_text TEXT NOT NULL, is_demo INTEGER DEFAULT 0, registration_milestone INTEGER DEFAULT 0, milestone_date TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event_briefs (event_id TEXT PRIMARY KEY REFERENCES events ON DELETE CASCADE, prompt TEXT NOT NULL, details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS team (event_id TEXT REFERENCES events ON DELETE CASCADE, member_id TEXT REFERENCES members, PRIMARY KEY(event_id,member_id));
CREATE TABLE IF NOT EXISTS milestones (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, title TEXT, due_date TEXT);
CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL, industry TEXT NOT NULL, description TEXT NOT NULL, tags TEXT NOT NULL, relationship TEXT DEFAULT '', sponsorship_type TEXT DEFAULT 'Financial', event_scope TEXT REFERENCES events ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS sponsors (id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events ON DELETE CASCADE, prospect_id TEXT REFERENCES profiles, stage TEXT NOT NULL, committed INTEGER DEFAULT 0 CHECK(committed>=0), draft TEXT DEFAULT '', follow_up_days INTEGER DEFAULT 5, follow_up_date TEXT, UNIQUE(event_id,prospect_id));
CREATE TABLE IF NOT EXISTS communications (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, sponsor_id TEXT REFERENCES sponsors ON DELETE CASCADE, kind TEXT, text TEXT, terms TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS receivables (sponsor_id TEXT PRIMARY KEY REFERENCES sponsors ON DELETE CASCADE, due_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS packages (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, name TEXT, amount INTEGER CHECK(amount>=0), benefits TEXT);
CREATE TABLE IF NOT EXISTS payments (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, sponsor_id TEXT REFERENCES sponsors ON DELETE CASCADE, amount INTEGER CHECK(amount>0), created_at TEXT);
CREATE TABLE IF NOT EXISTS budget (id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events ON DELETE CASCADE, category TEXT, planned INTEGER CHECK(planned>=0), adjustable INTEGER CHECK(adjustable>=0), UNIQUE(event_id,category));
CREATE TABLE IF NOT EXISTS expenses (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, category_id TEXT REFERENCES budget ON DELETE CASCADE, description TEXT, amount INTEGER CHECK(amount>0), created_at TEXT);
CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events ON DELETE CASCADE, title TEXT NOT NULL, description TEXT NOT NULL, department TEXT NOT NULL, owner_id TEXT REFERENCES members, status TEXT NOT NULL, priority TEXT NOT NULL, due_date TEXT NOT NULL, sponsor_id TEXT REFERENCES sponsors ON DELETE CASCADE, agent TEXT, created_at TEXT, completed_at TEXT);
CREATE TABLE IF NOT EXISTS dependencies (task_id TEXT REFERENCES tasks ON DELETE CASCADE, depends_on TEXT REFERENCES tasks ON DELETE CASCADE, PRIMARY KEY(task_id,depends_on),CHECK(task_id<>depends_on));
CREATE TABLE IF NOT EXISTS deliverables (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, sponsor_id TEXT REFERENCES sponsors ON DELETE CASCADE, task_id TEXT REFERENCES tasks ON DELETE CASCADE, evidence TEXT DEFAULT '', UNIQUE(sponsor_id,task_id));
CREATE TABLE IF NOT EXISTS participants (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, name TEXT, email TEXT COLLATE NOCASE, checked_in INTEGER DEFAULT 0, created_at TEXT, UNIQUE(event_id,email));
CREATE TABLE IF NOT EXISTS marketing (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, title TEXT, channel TEXT, body TEXT, status TEXT DEFAULT 'Draft', scheduled_date TEXT);
CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, trigger TEXT NOT NULL, request_id TEXT NOT NULL, input_hash TEXT NOT NULL, result TEXT, created_at TEXT, UNIQUE(event_id,request_id));
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, workflow_id TEXT REFERENCES workflows ON DELETE CASCADE, agent TEXT, trigger TEXT, tool TEXT, summary TEXT, mode TEXT, status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS risks (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, fingerprint TEXT, title TEXT, description TEXT, severity TEXT, source TEXT, impact TEXT, recommendation TEXT, agents TEXT, status TEXT DEFAULT 'Open', created_at TEXT, UNIQUE(event_id,fingerprint));
CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, risk_id TEXT REFERENCES risks ON DELETE CASCADE, workflow_id TEXT REFERENCES workflows ON DELETE CASCADE, title TEXT, description TEXT, actions TEXT, status TEXT DEFAULT 'Pending', created_at TEXT, decided_at TEXT, basis_balance INTEGER);
CREATE TABLE IF NOT EXISTS copilot_outbox (id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events ON DELETE CASCADE, sponsor_id TEXT NOT NULL REFERENCES sponsors ON DELETE CASCADE, message TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS disruptions (id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events ON DELETE CASCADE, title TEXT NOT NULL, changes TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decision_appeals (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK(target_type IN ('approval','risk','disruption','sponsor','run','poster')),
    target_id TEXT NOT NULL,
    title TEXT NOT NULL,
    reason TEXT NOT NULL,
    override_request TEXT DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('Flagged','Under Review','Overridden','Dismissed')),
    resolution_note TEXT DEFAULT '',
    submitted_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_appeals_event ON decision_appeals(event_id,target_type,target_id);
CREATE TABLE IF NOT EXISTS decision_audit_logs (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events ON DELETE CASCADE,
    appeal_id TEXT REFERENCES decision_appeals ON DELETE CASCADE,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    from_status TEXT DEFAULT '',
    to_status TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_event ON decision_audit_logs(event_id,created_at);
CREATE TABLE IF NOT EXISTS activity (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events ON DELETE CASCADE, title TEXT, description TEXT, agent TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_activity_event ON activity(event_id,created_at);
CREATE INDEX IF NOT EXISTS ix_runs_event ON runs(event_id,created_at);
"""

def uid():
    return uuid.uuid4().hex

def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',',':'))

def database_path():
    return Path(os.environ.get('CLUBOS_DB', Path(__file__).resolve().parents[1] / 'data' / 'clubos.sqlite3'))

def connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=90)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

@contextmanager
def transaction(write=False):
    c = connect()
    try:
        c.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def init_db():
    from .seed import bootstrap
    from .registration import SCHEMA as REGISTRATION_SCHEMA
    from .google_oauth import GOOGLE_OAUTH_SCHEMA
    from .gmail_integration import GMAIL_SCHEMA
    from .forms_integration import SCHEMA as FORMS_SCHEMA
    from .poster_studio import POSTER_SCHEMA
    c = connect()
    try:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript(SCHEMA + REGISTRATION_SCHEMA + GOOGLE_OAUTH_SCHEMA + GMAIL_SCHEMA + FORMS_SCHEMA + POSTER_SCHEMA)
        for table,column,kind in [
            ('google_oauth_states','code_verifier',"TEXT DEFAULT ''"),
            ('google_oauth_states','session_hash',"TEXT DEFAULT ''"),
            ('accounts','google_sub','TEXT'),
            ('clubs','available_funds','INTEGER NOT NULL DEFAULT 0'),
            ('tasks','completed_at','TEXT'),
            ('approvals','basis_balance','INTEGER'),
            ('sponsors','contact_email',"TEXT DEFAULT ''"),
            ('profiles','contact_email',"TEXT DEFAULT ''"),
            ('profiles','website',"TEXT DEFAULT ''"),
            ('disruptions','kind',"TEXT DEFAULT 'venue'"),
            ('disruptions','summary',"TEXT DEFAULT ''"),
            ('disruptions','actions_taken',"TEXT DEFAULT '[]'"),
            ('disruptions','notifications',"TEXT DEFAULT '[]'"),
        ]:
            if column not in {row['name'] for row in c.execute(f'PRAGMA table_info({table})')}:
                c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {kind}')
    finally:
        c.close()
    with transaction(True) as c:
        bootstrap(c)
        c.execute("""INSERT OR IGNORE INTO receivables SELECT s.id,e.start_date FROM sponsors s
            JOIN events e ON e.id=s.event_id WHERE s.stage='Confirmed' AND s.committed>0""")

def rows(c, sql, values=()):
    return [dict(r) for r in c.execute(sql, values)]

def insert(c, table, **fields):
    # Table and column identifiers come exclusively from internal call sites.
    key = fields.setdefault('id', uid())
    c.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", tuple(fields.values()))
    return key
