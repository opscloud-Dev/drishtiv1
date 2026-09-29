from datetime import datetime, timedelta, timezone

from app import admin, models
from app.database import SessionLocal

PASSWORD = "password123"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def signup_parent(client, email="devika@example.com", name="Devika", password=PASSWORD):
    r = client.post(
        "/auth/signup/parent", json={"name": name, "email": email, "password": password}
    )
    assert r.status_code == 201, r.text
    return r.json()


def signup_mentor(
    client, email="radhika@example.com", name="Radhika Nair",
    art_form="Mohiniyattam", password=PASSWORD,
):
    r = client.post(
        "/auth/signup/mentor",
        json={"name": name, "email": email, "password": password, "art_form": art_form},
    )
    assert r.status_code == 201, r.text
    return r.json()


def add_child(client, parent, name="Anjali", age=8, art="Mohiniyattam", level="Beginner"):
    r = client.post(
        "/children",
        headers=auth(parent["token"]),
        json={
            "parent_id": parent["id"], "name": name, "age": age,
            "art_form_interest": art, "level": level,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_teacher(slot_offsets_hours=(24,), name="Lakshmi Menon", art="Mohiniyattam"):
    """Create a Teacher directly in the DB with slots at now+offset hours."""
    db = SessionLocal()
    try:
        t = models.Teacher(name=name, art_form=art, bio="bio", verified=True, institution="Kalamandalam")
        db.add(t)
        db.flush()
        now = datetime.now(timezone.utc)
        slots = []
        for h in slot_offsets_hours:
            s = models.TeacherSlot(teacher_id=t.id, slot_time=now + timedelta(hours=h))
            db.add(s)
            slots.append(s)
        db.commit()
        return t.id, [s.id for s in slots]
    finally:
        db.close()


def book(client, parent, child_id, teacher_id, slot_id):
    return client.post(
        "/bookings",
        headers=auth(parent["token"]),
        json={
            "parent_id": parent["id"], "child_id": child_id,
            "teacher_id": teacher_id, "slot_id": slot_id,
        },
    )


def verified_mentor(client, email="radhika@example.com", slots=0):
    """A mentor who has submitted their profile and been approved by an admin."""
    mentor = signup_mentor(client, email=email)
    r = client.put(
        f"/mentors/{mentor['id']}/profile",
        headers=auth(mentor["token"]),
        json={"credential": "Kalamandalam graduate", "experience_years": 8, "bio": "Taught for 8 years."},
    )
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        teacher = admin.approve_mentor(db, email, slots=slots)
        teacher_id = teacher.id
    finally:
        db.close()
    return mentor, teacher_id
