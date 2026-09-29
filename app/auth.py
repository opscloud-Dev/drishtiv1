"""
Authentication and authorization.

- Passwords are hashed with bcrypt (never stored or logged in plain text).
- After signup/login the API returns a signed JWT; the app sends it back as
  'Authorization: Bearer <token>' on every protected call.
- Identity always comes from the token, never from an id the client claims.
  Endpoints that also carry an id in the URL/body check it matches the token.
"""
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import models
from .database import get_db  # imported first so .env is loaded before below

JWT_ALG = "HS256"
TOKEN_LIFETIME = timedelta(days=30)

_env_secret = os.getenv("JWT_SECRET")
MIN_SECRET_LEN = 32
if _env_secret:
    if len(_env_secret) < MIN_SECRET_LEN:
        raise RuntimeError(
            f"JWT_SECRET is too short ({len(_env_secret)} characters; need at "
            f"least {MIN_SECRET_LEN}). Generate a good one with:\n"
            f'  python3 -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    JWT_SECRET = _env_secret
else:
    # Fail safe, not open: a random per-process secret can't be guessed, but
    # everyone is signed out whenever the server restarts. Set JWT_SECRET in
    # .env / your host's environment variables to keep sessions alive.
    JWT_SECRET = secrets.token_urlsafe(48)
    print(
        "WARNING: JWT_SECRET is not set - using a temporary random one. "
        "Users will be logged out on every server restart. See README.",
        file=sys.stderr,
    )


# ---------------- passwords ----------------

def hash_password(password: str) -> str:
    rounds = int(os.getenv("BCRYPT_ROUNDS", "12"))
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)
    ).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # malformed hash, or a password over bcrypt's 72-byte limit
        return False


# Verified against when a login email doesn't exist, so "no such account" and
# "wrong password" take the same time and can't be told apart by timing.
DUMMY_HASH = hash_password("not-a-real-password")


# ---------------- tokens ----------------

def create_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "role": role, "iat": now, "exp": now + TOKEN_LIFETIME},
        JWT_SECRET,
        algorithm=JWT_ALG,
    )


# ---------------- request identity ----------------

_bearer = HTTPBearer(auto_error=False)


class Principal:
    """The authenticated caller: who they are, and their loaded DB row."""

    def __init__(self, user_id: str, role: str, user):
        self.id = user_id
        self.role = role
        self.user = user


def _unauthorized(detail: str = "Please sign in again") -> HTTPException:
    return HTTPException(
        status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Principal:
    if creds is None:
        raise _unauthorized("Sign in required")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        raise _unauthorized("Your session has expired. Please sign in again")

    role, sub = payload.get("role"), payload.get("sub")
    model = {"parent": models.Parent, "mentor": models.Mentor}.get(role)
    if model is None or not sub:
        raise _unauthorized()

    # A valid token for an account that no longer exists (e.g. after a
    # database reset) is treated as signed out, not as a server error.
    user = db.get(model, sub)
    if user is None:
        raise _unauthorized("Your account was not found. Please sign in again")
    return Principal(sub, role, user)


def require_parent(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != "parent":
        raise HTTPException(403, "This action is for parent accounts")
    return principal


def require_mentor(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != "mentor":
        raise HTTPException(403, "This action is for mentor accounts")
    return principal
