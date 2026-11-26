"""Unified Google OAuth 2.0 integration for ClubOS.

Handles a single OAuth consent flow that grants access to both Gmail and
Google Forms APIs. Tokens are stored per-club in ``google_oauth_tokens``
and refreshed automatically when they expire.
"""

import logging
import os
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import auth, db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Google libraries – imported lazily so the app still boots when deps
# are missing (the ``/status`` endpoint reports ``available: false``).
# ---------------------------------------------------------------------------

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build

    _GOOGLE_LIBS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _GOOGLE_LIBS_AVAILABLE = False

# All scopes requested in a single consent screen.
SCOPES = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.getenv("GOOGLE_CLIENT_SECRET", "").strip()


def _redirect_uri() -> str:
    return os.getenv(
        "GOOGLE_REDIRECT_URI",
        "http://localhost:8017/api/integrations/google/callback",
    ).strip()


def is_configured() -> bool:
    return bool(_GOOGLE_LIBS_AVAILABLE and _client_id() and _client_secret())


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

GOOGLE_OAUTH_SCHEMA = """\
CREATE TABLE IF NOT EXISTS google_oauth_tokens (
    id            TEXT PRIMARY KEY,
    club_id       TEXT NOT NULL,
    access_token  TEXT NOT NULL,
    refresh_token TEXT,
    token_expiry  TEXT,
    email         TEXT,
    scopes        TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_google_oauth_club ON google_oauth_tokens(club_id);
CREATE TABLE IF NOT EXISTS google_oauth_states (
    state         TEXT PRIMARY KEY,
    club_id       TEXT NOT NULL,
    code_verifier TEXT DEFAULT '',
    expires_at    INTEGER NOT NULL
);
"""


def init_google_oauth_db() -> None:
    """Create the Google OAuth tables if they don't exist."""
    conn = db.connect()
    try:
        conn.executescript(GOOGLE_OAUTH_SCHEMA)
        if "code_verifier" not in {
            r["name"] for r in conn.execute("PRAGMA table_info(google_oauth_states)")
        }:
            conn.execute(
                "ALTER TABLE google_oauth_states ADD COLUMN code_verifier TEXT DEFAULT ''"
            )
    finally:
        conn.close()


def _store_tokens(
    club_id: str,
    access_token: str,
    refresh_token: str | None,
    token_expiry: datetime | None,
    email: str | None,
    scopes: list[str],
) -> None:
    """Upsert a token row for *club_id*."""
    expiry_str = token_expiry.isoformat() if token_expiry else None
    scope_str = " ".join(scopes)
    with db.transaction(write=True) as conn:
        existing = conn.execute(
            "SELECT refresh_token FROM google_oauth_tokens WHERE club_id = ?",
            (club_id,),
        ).fetchone()
        kept_refresh = refresh_token or (existing["refresh_token"] if existing else "")
        conn.execute(
            "DELETE FROM google_oauth_tokens WHERE club_id = ?", (club_id,)
        )
        db.insert(
            conn,
            "google_oauth_tokens",
            club_id=club_id,
            access_token=access_token,
            refresh_token=kept_refresh,
            token_expiry=expiry_str,
            email=email,
            scopes=scope_str,
            created_at=db.now(),
        )


def _load_token_row(club_id: str) -> dict | None:
    """Return the token row for *club_id*, or ``None``."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM google_oauth_tokens WHERE club_id = ?",
            (club_id,),
        ).fetchone()
    return dict(row) if row else None


def _delete_tokens(club_id: str) -> None:
    with db.transaction(write=True) as conn:
        conn.execute(
            "DELETE FROM google_oauth_tokens WHERE club_id = ?", (club_id,)
        )


# ---------------------------------------------------------------------------
# Credential helpers (public API for other modules)
# ---------------------------------------------------------------------------


def get_credentials(club_id: str):
    """Return valid ``google.oauth2.credentials.Credentials`` or ``None``.

    Automatically refreshes the access-token using the stored refresh-token
    when the current one is expired.
    """
    if not is_configured():
        return None

    row = _load_token_row(club_id)
    if not row:
        return None

    creds = Credentials(
        token=row["access_token"],
        refresh_token=row["refresh_token"] or None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=_client_id(),
        client_secret=_client_secret(),
        scopes=row["scopes"].split() if row["scopes"] else SCOPES,
    )

    if row["token_expiry"]:
        creds.expiry = datetime.fromisoformat(row["token_expiry"]).replace(
            tzinfo=None
        )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleAuthRequest())
            _store_tokens(
                club_id=club_id,
                access_token=creds.token,
                refresh_token=creds.refresh_token,
                token_expiry=creds.expiry.replace(tzinfo=timezone.utc)
                if creds.expiry
                else None,
                email=row["email"],
                scopes=list(creds.scopes) if creds.scopes else SCOPES,
            )
            logger.info("Google OAuth token refreshed for club %s", club_id)
        except Exception:
            logger.exception(
                "Failed to refresh Google OAuth token for club %s", club_id
            )
            return None

    return creds


def get_gmail_service(club_id: str):
    """Return an authenticated Gmail API service or ``None``."""
    creds = get_credentials(club_id)
    if not creds:
        return None
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_forms_service(club_id: str):
    """Return an authenticated Google Forms API service or ``None``."""
    creds = get_credentials(club_id)
    if not creds:
        return None
    return build("forms", "v1", credentials=creds, cache_discovery=False)


def is_club_connected(club_id: str) -> bool:
    """Return True if *club_id* has valid stored Google credentials."""
    if not is_configured():
        return False
    return _load_token_row(club_id) is not None


# ---------------------------------------------------------------------------
# OAuth flow builder
# ---------------------------------------------------------------------------


def _build_flow(state: str | None = None) -> "Flow":
    """Create a ``google_auth_oauthlib.flow.Flow`` for the web server flow."""
    redirect = _redirect_uri()
    client_config = {
        "web": {
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=state,
        redirect_uri=redirect,
    )


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/integrations/google", tags=["google-oauth"])


@router.get("/status")
def google_status(club: auth.Workspace):
    """Check whether a Google account is connected for this club."""
    if not is_configured():
        return {"connected": False, "email": None, "available": False}

    row = _load_token_row(club["id"])
    if row:
        return {
            "connected": True,
            "email": row.get("email"),
            "available": True,
        }
    return {"connected": False, "email": None, "available": True}


@router.get("/auth-url")
def google_auth_url(club: auth.Workspace):
    """Generate the Google OAuth authorization URL."""
    if not is_configured():
        raise HTTPException(
            503,
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in .env.",
        )

    state = secrets.token_urlsafe(24)
    now_ts = int(time.time())
    flow = _build_flow(state=state)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    code_verifier = getattr(flow, "code_verifier", None) or ""
    with db.transaction(write=True) as conn:
        if "code_verifier" not in {
            r["name"] for r in conn.execute("PRAGMA table_info(google_oauth_states)")
        }:
            conn.execute(
                "ALTER TABLE google_oauth_states ADD COLUMN code_verifier TEXT DEFAULT ''"
            )
        conn.execute("DELETE FROM google_oauth_states WHERE expires_at<=?", (now_ts,))
        conn.execute(
            "INSERT INTO google_oauth_states(state, club_id, code_verifier, expires_at) VALUES (?, ?, ?, ?)",
            (state, club["id"], code_verifier, now_ts + 600),
        )
    return {"url": authorization_url}


@router.get("/callback")
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Handle the OAuth 2.0 callback from Google."""
    if error:
        logger.warning("Google OAuth callback received error: %s", error)
        return RedirectResponse("/?google_auth=error#dashboard")

    if not code:
        return RedirectResponse("/?google_auth=missing_code#dashboard")

    if not is_configured():
        return RedirectResponse("/?google_auth=not_configured#dashboard")

    club_id = None
    code_verifier = None
    now_ts = int(time.time())
    if state:
        with db.transaction(write=True) as conn:
            if "code_verifier" not in {
                r["name"] for r in conn.execute("PRAGMA table_info(google_oauth_states)")
            }:
                conn.execute(
                    "ALTER TABLE google_oauth_states ADD COLUMN code_verifier TEXT DEFAULT ''"
                )
            row = conn.execute(
                "SELECT club_id, code_verifier FROM google_oauth_states WHERE state=? AND expires_at>?",
                (state, now_ts),
            ).fetchone()
            if row:
                club_id = row["club_id"]
                code_verifier = row["code_verifier"] or None
                conn.execute("DELETE FROM google_oauth_states WHERE state=?", (state,))

    if not club_id:
        with db.transaction() as conn:
            current = auth.session(conn, request)
        if current and current.get("club"):
            club_id = current["club"]["id"]

    if not club_id:
        return RedirectResponse("/?google_auth=no_session#dashboard")

    try:
        flow = _build_flow(state=state)
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(code=code)
        creds = flow.credentials

        # Fetch connected Gmail address using gmail.readonly scope (works without userinfo scope).
        email = None
        try:
            gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
            profile = gmail.users().getProfile(userId="me").execute()
            email = profile.get("emailAddress")
        except Exception:
            logger.debug("Gmail profile lookup failed, trying oauth2 userinfo", exc_info=True)
            try:
                oauth2 = build("oauth2", "v2", credentials=creds, cache_discovery=False)
                user_info = oauth2.userinfo().get().execute()
                email = user_info.get("email")
            except Exception:
                logger.warning("Could not fetch Google user email", exc_info=True)

        _store_tokens(
            club_id=club_id,
            access_token=creds.token,
            refresh_token=creds.refresh_token,
            token_expiry=creds.expiry.replace(tzinfo=timezone.utc)
            if creds.expiry
            else None,
            email=email,
            scopes=list(creds.scopes) if creds.scopes else SCOPES,
        )
        logger.info("Google OAuth tokens stored for club %s (email=%s)", club_id, email)
        return RedirectResponse("/?google_auth=success#dashboard")

    except Exception:
        logger.exception("Google OAuth token exchange failed")
        return RedirectResponse("/?google_auth=error#dashboard")


@router.post("/disconnect")
def google_disconnect(club: auth.Workspace):
    """Remove stored Google OAuth tokens for this club."""
    _delete_tokens(club["id"])
    return {"ok": True, "connected": False}
