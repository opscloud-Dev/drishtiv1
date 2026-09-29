import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app import admin, models
from app.database import SessionLocal, engine
from app.main import check_schema_current
from .helpers import PASSWORD, auth, signup_mentor, signup_parent


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# ---------- signup ----------

def test_signup_returns_token_id_and_name(client):
    p = signup_parent(client, name="Devika")
    assert p["role"] == "parent" and p["name"] == "Devika"
    assert p["token"] and p["id"]


def test_password_is_stored_hashed_not_plain(client):
    signup_parent(client)
    db = SessionLocal()
    try:
        stored = db.query(models.Parent).one().password_hash
    finally:
        db.close()
    assert stored != PASSWORD and stored.startswith("$2")  # bcrypt


def test_duplicate_email_is_rejected_case_insensitively(client):
    signup_parent(client, email="devika@example.com")
    r = client.post(
        "/auth/signup/parent",
        json={"name": "Other", "email": "DEVIKA@Example.com", "password": PASSWORD},
    )
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_same_email_can_be_both_parent_and_mentor(client):
    signup_parent(client, email="both@example.com")
    signup_mentor(client, email="both@example.com")  # separate account types


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "A", "email": "a@example.com", "password": "short"},          # too short
        {"name": "A", "email": "not-an-email", "password": PASSWORD},          # bad email
        {"name": "   ", "email": "a@example.com", "password": PASSWORD},       # blank name
        {"name": "A", "email": "a@example.com", "password": "x" * 80},         # > 72 bytes
    ],
)
def test_signup_validation(client, payload):
    assert client.post("/auth/signup/parent", json=payload).status_code == 422


def test_mentor_signup_rejects_unknown_art_form(client):
    r = client.post(
        "/auth/signup/mentor",
        json={"name": "A", "email": "a@example.com", "password": PASSWORD, "art_form": "Juggling"},
    )
    assert r.status_code == 422


# ---------- login ----------

def test_login_success(client):
    signup_parent(client, email="devika@example.com")
    r = client.post(
        "/auth/login",
        json={"role": "parent", "email": "  Devika@Example.com ", "password": PASSWORD},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "parent"


def test_wrong_password_and_unknown_email_give_the_same_error(client):
    signup_parent(client, email="devika@example.com")
    wrong_pw = client.post(
        "/auth/login", json={"role": "parent", "email": "devika@example.com", "password": "nope-nope"}
    )
    no_user = client.post(
        "/auth/login", json={"role": "parent", "email": "ghost@example.com", "password": PASSWORD}
    )
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()  # can't tell which emails exist


def test_login_with_the_wrong_role_fails(client):
    signup_parent(client, email="devika@example.com")
    r = client.post(
        "/auth/login", json={"role": "mentor", "email": "devika@example.com", "password": PASSWORD}
    )
    assert r.status_code == 401


# ---------- tokens ----------

def test_protected_routes_need_a_token(client):
    p = signup_parent(client)
    assert client.get(f"/parents/{p['id']}/children").status_code == 401
    r = client.get(f"/parents/{p['id']}/children", headers=auth("garbage.token.value"))
    assert r.status_code == 401


def test_expired_token_is_rejected(client):
    p = signup_parent(client)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    expired = jwt.encode(
        {"sub": p["id"], "role": "parent", "exp": past},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    assert client.get(f"/parents/{p['id']}/children", headers=auth(expired)).status_code == 401


def test_token_signed_with_another_secret_is_rejected(client):
    p = signup_parent(client)
    forged = jwt.encode(
        {"sub": p["id"], "role": "parent", "exp": datetime.now(timezone.utc) + timedelta(days=1)},
        "a-completely-different-secret-of-sufficient-length", algorithm="HS256",
    )
    assert client.get(f"/parents/{p['id']}/children", headers=auth(forged)).status_code == 401


def test_valid_token_for_a_deleted_account_is_a_401_not_a_500(client):
    """What a tester's phone sees after you reset the database."""
    p = signup_parent(client)
    db = SessionLocal()
    try:
        db.query(models.Parent).delete()
        db.commit()
    finally:
        db.close()
    assert client.get(f"/parents/{p['id']}/children", headers=auth(p["token"])).status_code == 401


def test_parent_and_mentor_tokens_are_not_interchangeable(client):
    parent = signup_parent(client)
    mentor = signup_mentor(client)
    assert client.get(f"/mentors/{mentor['id']}", headers=auth(parent["token"])).status_code == 403
    assert client.get(f"/parents/{parent['id']}/children", headers=auth(mentor["token"])).status_code == 403


# ---------- admin: password reset ----------

def test_admin_set_password(client):
    signup_parent(client, email="devika@example.com")
    db = SessionLocal()
    try:
        admin.set_password(db, "parent", "devika@example.com", "brand-new-pass")
    finally:
        db.close()
    old = client.post("/auth/login", json={"role": "parent", "email": "devika@example.com", "password": PASSWORD})
    new = client.post("/auth/login", json={"role": "parent", "email": "devika@example.com", "password": "brand-new-pass"})
    assert old.status_code == 401 and new.status_code == 200


def test_admin_set_password_validates(client):
    signup_parent(client, email="devika@example.com")
    db = SessionLocal()
    try:
        with pytest.raises(admin.AdminError):
            admin.set_password(db, "parent", "devika@example.com", "short")
        with pytest.raises(admin.AdminError):
            admin.set_password(db, "parent", "nobody@example.com", "long-enough-pass")
    finally:
        db.close()


# ---------- stale database detection ----------

def test_startup_check_explains_an_outdated_database(client):
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE parents CASCADE"))
        conn.execute(text("CREATE TABLE parents (id uuid primary key, name text, email text)"))
    with pytest.raises(RuntimeError, match="reset_db"):
        check_schema_current()


def test_a_weak_jwt_secret_is_refused_at_startup():
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-c", "import app.auth"],
        env={**os.environ, "JWT_SECRET": "too-short"},
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "JWT_SECRET is too short" in result.stderr
