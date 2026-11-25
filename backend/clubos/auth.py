"""Local organizer accounts, workspace setup, and server-side sessions."""
import hashlib
import hmac
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

from . import db
from .seed import CLUB

router = APIRouter(prefix="/api/auth")
COOKIE = "clubos_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
Password = Annotated[str, StringConstraints(min_length=8, max_length=200)]
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email
    password: Password


class Registration(Credentials):
    name: Name


class ClubDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    college: Name
    role: Name = "Organizer"


def hash_password(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def session(conn, request):
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 80:
        return None
    row = conn.execute(
        """SELECT s.demo, a.id account_id, a.name, a.email, c.id club_id, c.name club_name, c.college,
        (SELECT role FROM members WHERE club_id=c.id ORDER BY rowid LIMIT 1) role
        FROM sessions s
        LEFT JOIN accounts a ON a.id=s.account_id
        LEFT JOIN clubs c ON c.id=CASE WHEN s.demo=1 THEN ? ELSE a.club_id END
        WHERE s.id=? AND s.expires_at>?""",
        (CLUB, token_hash(token), int(time.time())),
    ).fetchone()
    if row is None:
        return None
    return {
        "account_id": row["account_id"],
        "name": row["name"] or "Demo organizer",
        "email": row["email"],
        "role": row["role"] or "Organizer",
        "demo": bool(row["demo"]),
        "club": {"id": row["club_id"], "name": row["club_name"], "college": row["college"]} if row["club_id"] else None,
    }


def account(request: Request):
    with db.transaction() as conn:
        current = session(conn, request)
    if not current:
        raise HTTPException(401, "Log in to open this workspace.")
    return current


def workspace(current: Annotated[dict, Depends(account)]):
    if not current["club"]:
        raise HTTPException(403, "Create your club workspace first.")
    return current["club"]


Workspace = Annotated[dict, Depends(workspace)]


def authorize_event(conn, event_id, club_id):
    if conn.execute("SELECT 1 FROM events WHERE id=? AND club_id=?", (event_id, club_id)).fetchone() is None:
        raise HTTPException(404, "Event not found.")


def open_session(conn, request, response, account_id=None, demo=False):
    old = request.cookies.get(COOKIE)
    if old:
        conn.execute("DELETE FROM sessions WHERE id=?", (token_hash(old),))
    now = int(time.time())
    conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
    token = secrets.token_urlsafe(32)
    db.insert(conn, "sessions", id=token_hash(token), account_id=account_id, demo=int(demo), expires_at=now+SESSION_SECONDS)
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=request.url.scheme == "https", samesite="lax", path="/")


@router.get("/session")
def read_session(request: Request):
    with db.transaction() as conn:
        return {"session": session(conn, request)}


@router.post("/signup", status_code=201)
def signup(data: Registration, request: Request, response: Response):
    salt = secrets.token_hex(16)
    digest = hash_password(data.password, salt)
    email = data.email.lower()
    with db.transaction(write=True) as conn:
        if conn.execute("SELECT 1 FROM accounts WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "An account already uses this email. Log in to continue.")
        account_id = db.insert(conn, "accounts", name=data.name, email=email, salt=salt, digest=digest)
        open_session(conn, request, response, account_id=account_id)
    return {"ok": True}


@router.post("/login")
def login(data: Credentials, request: Request, response: Response):
    with db.transaction() as conn:
        row = conn.execute("SELECT id,salt,digest FROM accounts WHERE email=?", (data.email.lower(),)).fetchone()
    attempted = hash_password(data.password, row["salt"] if row else "0"*32)
    if not row or not hmac.compare_digest(row["digest"], attempted):
        raise HTTPException(401, "Email or password is incorrect.")
    with db.transaction(write=True) as conn:
        open_session(conn, request, response, account_id=row["id"])
    return {"ok": True}


@router.post("/demo")
def open_demo(request: Request, response: Response):
    with db.transaction(write=True) as conn:
        open_session(conn, request, response, demo=True)
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        with db.transaction(write=True) as conn:
            conn.execute("DELETE FROM sessions WHERE id=?", (token_hash(token),))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/club", status_code=201)
def create_club(data: ClubDetails, current: Annotated[dict, Depends(account)]):
    if current["demo"]:
        raise HTTPException(403, "Create an organizer account to set up a club.")
    with db.transaction(write=True) as conn:
        row = conn.execute("SELECT club_id FROM accounts WHERE id=?", (current["account_id"],)).fetchone()
        if row["club_id"]:
            raise HTTPException(409, "Your account already has a club workspace.")
        club_id = db.insert(conn, "clubs", name=data.name, college=data.college)
        db.insert(conn, "members", club_id=club_id, name=current["name"], role=data.role, department="Planning")
        conn.execute("UPDATE accounts SET club_id=? WHERE id=?", (club_id, current["account_id"]))
    return {"id": club_id, "name": data.name, "college": data.college}
