"""Password hashing, JWT tokens and the current-user dependency."""
import hashlib
import hmac
import os
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .db import db

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


def create_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": int(time.time()) + settings.jwt_hours * 3600}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if not creds:
        raise HTTPException(401, "Sign in to continue.")
    try:
        user_id = int(jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(401, "Your session has expired. Sign in again.")
    with db() as conn:
        row = conn.execute("SELECT id, email, name FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(401, "Account not found.")
    return dict(row)
