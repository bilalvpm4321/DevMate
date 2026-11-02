import secrets
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..db import db
from ..schemas import LoginRequest, RegisterRequest
from ..security import create_token, current_user, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _session(user: dict) -> dict:
    return {"token": create_token(user["id"]), "user": {"id": user["id"], "name": user["name"], "email": user["email"]}}


@router.post("/register")
def register(body: RegisterRequest):
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, name, password_hash) VALUES (?,?,?)",
                (body.email.lower(), body.name, hash_password(body.password)),
            )
            return _session({"id": cur.lastrowid, "name": body.name, "email": body.email.lower()})
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")


@router.post("/login")
def login(body: LoginRequest):
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (body.email.lower(),)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Email or password is incorrect.")
    return _session(dict(row))


@router.post("/guest")
def guest():
    """Instant demo account so visitors can try DevMate without registering."""
    tag = secrets.token_hex(4)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (?,?,?)",
            (f"guest-{tag}@guest.local", f"Guest {tag}", hash_password(secrets.token_hex(16))),
        )
        return _session({"id": cur.lastrowid, "name": f"Guest {tag}", "email": f"guest-{tag}@guest.local"})


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return user
