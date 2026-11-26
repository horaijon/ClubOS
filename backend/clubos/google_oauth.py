"""Unified Google OAuth 2.0 integration for ClubOS.

Handles a single OAuth consent flow that grants access to both Gmail and
Google Forms APIs. Tokens are stored per-club in ``google_oauth_tokens``
and refreshed automatically when they expire.
"""

import json
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
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
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
    port = os.getenv("PORT", "8018")
    return os.getenv(
        "GOOGLE_REDIRECT_URI",
        f"http://127.0.0.1:{port}/api/integrations/google/callback",
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
    session_hash  TEXT DEFAULT '',
    expires_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS google_pending_tokens (
    account_id    TEXT PRIMARY KEY REFERENCES accounts ON DELETE CASCADE,
    tokens        TEXT NOT NULL
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
# Sign in with Google
# ---------------------------------------------------------------------------

LOGIN_COOKIE = "clubos_google_login"


def _identity(creds) -> dict | None:
    """Return the verified Google identity from *creds*, or ``None``."""
    token = getattr(creds, "id_token", None)
    if not token:
        return None
    try:
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(
            token, GoogleAuthRequest(), _client_id(), clock_skew_in_seconds=10
        )
    except Exception:
        logger.warning("Could not verify the Google ID token", exc_info=True)
        return None
    if not claims.get("sub") or not claims.get("email") or claims.get("email_verified") is not True:
        return None
    return {
        "sub": claims["sub"],
        "email": claims["email"].lower(),
        "name": (claims.get("name") or claims["email"].split("@")[0])[:120],
    }


def _token_fields(creds, email: str | None) -> dict:
    expiry = creds.expiry.replace(tzinfo=timezone.utc) if creds.expiry else None
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_expiry": expiry,
        "email": email,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }


def _connect_if_free(club_id: str, tokens: dict) -> None:
    """Connect a club without replacing a different Google account it already uses."""
    row = _load_token_row(club_id)
    if row and (row.get("email") or "").lower() != (tokens["email"] or "").lower():
        return
    _store_tokens(club_id=club_id, **tokens)


def attach_pending(account_id: str, club_id: str) -> None:
    """Connect a newly created club using the tokens from the Google sign-up."""
    with db.transaction(write=True) as conn:
        row = conn.execute(
            "SELECT tokens FROM google_pending_tokens WHERE account_id=?", (account_id,)
        ).fetchone()
        conn.execute("DELETE FROM google_pending_tokens WHERE account_id=?", (account_id,))
    if row:
        tokens = json.loads(row["tokens"])
        if tokens["token_expiry"]:
            tokens["token_expiry"] = datetime.fromisoformat(tokens["token_expiry"])
        _connect_if_free(club_id, tokens)


def _finish_login(request: Request, code: str, state: str, code_verifier: str | None):
    """Exchange the code, find or create the account, and open its session."""
    try:
        flow = _build_flow(state=state)
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(code=code)
        creds = flow.credentials
    except Exception:
        logger.exception("Google sign-in token exchange failed")
        return RedirectResponse("/?google_login=error#login")
    who = _identity(creds)
    if not who:
        return RedirectResponse("/?google_login=error#login")

    tokens = _token_fields(creds, who["email"])
    with db.transaction(write=True) as conn:
        account = conn.execute(
            "SELECT id, club_id FROM accounts WHERE google_sub=?", (who["sub"],)
        ).fetchone()
        if account:
            account_id, club_id = account["id"], account["club_id"]
        elif conn.execute("SELECT 1 FROM accounts WHERE email=?", (who["email"],)).fetchone():
            # Password sign-up never verified this email, so ownership of the
            # account must be proven once (password login, then Connect Google).
            return RedirectResponse("/?google_login=link_required#login")
        else:
            salt = secrets.token_hex(16)
            account_id = db.insert(
                conn, "accounts", name=who["name"], email=who["email"], salt=salt,
                digest=auth.hash_password(secrets.token_urlsafe(32), salt),
                google_sub=who["sub"],
            )
            club_id = None
        if not club_id:
            conn.execute(
                "INSERT OR REPLACE INTO google_pending_tokens(account_id, tokens) VALUES (?, ?)",
                (account_id, db.encode({**tokens, "token_expiry": tokens["token_expiry"] and tokens["token_expiry"].isoformat()})),
            )
    if club_id:
        _connect_if_free(club_id, tokens)

    response = RedirectResponse("/#dashboard" if club_id else "/#setup")
    with db.transaction(write=True) as conn:
        auth.open_session(conn, request, response, account_id=account_id)
    response.delete_cookie(LOGIN_COOKIE, path="/")
    return response


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


@router.get("/login-available")
def google_login_available():
    return {"available": is_configured()}


@router.get("/login")
def google_login(request: Request):
    """Send the browser to Google to sign in and grant Gmail and Forms access."""
    if not is_configured():
        return RedirectResponse("/?google_login=not_configured#login")
    if request.url.hostname in ("localhost", "127.0.0.1"):
        expected = str(request.base_url).rstrip("/") + "/api/integrations/google/callback"
        if _redirect_uri() != expected:
            return RedirectResponse("/?google_login=wrong_address#login")
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(32)
    now_ts = int(time.time())
    flow = _build_flow(state=state)
    authorization_url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    with db.transaction(write=True) as conn:
        conn.execute("DELETE FROM google_oauth_states WHERE expires_at<=?", (now_ts,))
        # An empty club_id marks a sign-in; the nonce cookie ties it to this browser.
        conn.execute(
            "INSERT INTO google_oauth_states(state, club_id, code_verifier, session_hash, expires_at) VALUES (?, '', ?, ?, ?)",
            (state, getattr(flow, "code_verifier", None) or "", auth.token_hash(nonce), now_ts + 600),
        )
    response = RedirectResponse(authorization_url)
    response.set_cookie(
        LOGIN_COOKIE, nonce, max_age=600, httponly=True,
        secure=request.url.scheme == "https", samesite="lax", path="/",
    )
    return response


@router.get("/auth-url")
def google_auth_url(request: Request, club: auth.Workspace):
    """Generate the Google OAuth authorization URL."""
    if not is_configured():
        raise HTTPException(
            503,
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in .env.",
        )

    if request.url.hostname in ("localhost","127.0.0.1"):
        expected=str(request.base_url).rstrip("/")+"/api/integrations/google/callback"
        if _redirect_uri()!=expected:
            raise HTTPException(409,"Open ClubOS at the same browser address configured for its Google OAuth callback.")
    session_token=request.cookies.get(auth.COOKIE)
    if not session_token:
        raise HTTPException(401,"Log in before connecting Google.")
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
            "INSERT INTO google_oauth_states(state, club_id, code_verifier, session_hash, expires_at) VALUES (?, ?, ?, ?, ?)",
            (state, club["id"], code_verifier, auth.token_hash(session_token), now_ts + 600),
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
    login = None
    if state:
        with db.transaction() as conn:
            login = conn.execute(
                "SELECT code_verifier, session_hash FROM google_oauth_states WHERE state=? AND club_id='' AND expires_at>?",
                (state, int(time.time())),
            ).fetchone()
    if login:
        nonce = request.cookies.get(LOGIN_COOKIE)
        if not nonce or auth.token_hash(nonce) != login["session_hash"]:
            return RedirectResponse("/?google_login=error#login")
        with db.transaction(write=True) as conn:
            used = conn.execute("DELETE FROM google_oauth_states WHERE state=?", (state,)).rowcount
        if error or not code or not used or not is_configured():
            return RedirectResponse("/?google_login=error#login")
        return _finish_login(request, code, state, login["code_verifier"] or None)

    if error:
        logger.warning("Google OAuth callback received error: %s", error)
        return RedirectResponse("/?google_auth=error#dashboard")

    if not code:
        return RedirectResponse("/?google_auth=missing_code#dashboard")

    if not is_configured():
        return RedirectResponse("/?google_auth=not_configured#dashboard")

    session_token=request.cookies.get(auth.COOKIE)
    if not state or not session_token:
        return RedirectResponse("/?google_auth=no_session#dashboard")
    with db.transaction(write=True) as conn:
        current=auth.session(conn,request)
        row=conn.execute("""SELECT club_id,code_verifier,session_hash FROM google_oauth_states
            WHERE state=? AND expires_at>?""",(state,int(time.time()))).fetchone()
        if not row or not current or not current.get("club") or (
            row["club_id"]!=current["club"]["id"] or row["session_hash"]!=auth.token_hash(session_token)
        ):
            return RedirectResponse("/?google_auth=no_session#dashboard")
        club_id=row["club_id"]
        code_verifier=row["code_verifier"] or None
        conn.execute("DELETE FROM google_oauth_states WHERE state=?",(state,))

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
        who = _identity(creds)
        if who and current.get("account_id"):
            # Connecting while logged in links this Google identity for future sign-ins.
            with db.transaction(write=True) as conn:
                conn.execute(
                    """UPDATE accounts SET google_sub=? WHERE id=? AND COALESCE(google_sub,'')=''
                       AND NOT EXISTS(SELECT 1 FROM accounts WHERE google_sub=?)""",
                    (who["sub"], current["account_id"], who["sub"]),
                )
        return RedirectResponse("/?google_auth=success#dashboard")

    except Exception:
        logger.exception("Google OAuth token exchange failed")
        return RedirectResponse("/?google_auth=error#dashboard")


@router.post("/disconnect")
def google_disconnect(club: auth.Workspace):
    """Remove stored Google OAuth tokens for this club."""
    _delete_tokens(club["id"])
    return {"ok": True, "connected": False}
