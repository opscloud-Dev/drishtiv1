from datetime import datetime, timedelta, timezone

import pytest

from app import admin, models
from app.database import SessionLocal
from .helpers import (
    add_child, auth, book, make_teacher, signup_mentor, signup_parent, verified_mentor,
)


def _submit(client, mentor, **overrides):
    body = {"credential": "Kalamandalam graduate", "experience_years": 8, "bio": "Taught for 8 years."}
    return client.put(f"/mentors/{mentor['id']}/profile", headers=auth(mentor["token"]), json={**body, **overrides})


# ---------- verification lifecycle: pending -> under_review -> verified ----------

def test_new_mentor_is_pending_with_an_empty_profile(client):
    m = signup_mentor(client)
    r = client.get(f"/mentors/{m['id']}", headers=auth(m["token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["verification_status"] == "pending"
    assert body["art_form"] == "Mohiniyattam"
    assert body["credential"] is None and body["linked_teacher_id"] is None


def test_submitting_the_profile_moves_to_under_review(client):
    m = signup_mentor(client)
    r = _submit(client, m)
    assert r.status_code == 200
    body = r.json()
    assert body["verification_status"] == "under_review"
    assert body["credential"] == "Kalamandalam graduate" and body["experience_years"] == 8


def test_profile_can_be_resubmitted(client):
    m = signup_mentor(client)
    _submit(client, m)
    r = _submit(client, m, bio="Updated bio")
    assert r.status_code == 200 and r.json()["bio"] == "Updated bio"
    assert r.json()["verification_status"] == "under_review"


@pytest.mark.parametrize(
    "bad",
    [{"credential": ""}, {"credential": "   "}, {"experience_years": -1}, {"experience_years": 99}, {"bio": ""}],
)
def test_profile_validation(client, bad):
    m = signup_mentor(client)
    assert _submit(client, m, **bad).status_code == 422


def test_mentor_cannot_edit_another_mentors_profile(client):
    a = signup_mentor(client, email="a@example.com")
    b = signup_mentor(client, email="b@example.com")
    r = client.put(f"/mentors/{a['id']}/profile", headers=auth(b["token"]),
                   json={"credential": "Fake credential", "experience_years": 1, "bio": "x"})
    assert r.status_code == 403


def test_approving_makes_a_mentor_verified_and_bookable(client):
    mentor, teacher_id = verified_mentor(client, slots=3)

    body = client.get(f"/mentors/{mentor['id']}", headers=auth(mentor["token"])).json()
    assert body["verification_status"] == "verified"
    assert body["linked_teacher_id"] == teacher_id

    # parents can now find them, with the bookable slots the admin added
    (t,) = client.get("/teachers").json()
    assert t["id"] == teacher_id
    assert t["name"] == "Radhika Nair"
    assert t["art_form"] == "Mohiniyattam" and t["verified"] is True
    assert t["institution"] == "Kalamandalam graduate"
    assert len(t["teacher_slots"]) == 3


def test_approve_requires_a_submitted_profile_unless_forced(client):
    signup_mentor(client, email="new@example.com")
    db = SessionLocal()
    try:
        with pytest.raises(admin.AdminError, match="hasn't submitted"):
            admin.approve_mentor(db, "new@example.com")
        admin.approve_mentor(db, "new@example.com", force=True)  # allowed when forced
        with pytest.raises(admin.AdminError, match="already verified"):
            admin.approve_mentor(db, "new@example.com", force=True)
        with pytest.raises(admin.AdminError, match="No mentor"):
            admin.approve_mentor(db, "ghost@example.com")
    finally:
        db.close()


def test_admin_can_override_the_badge_text(client):
    signup_mentor(client, email="m@example.com")
    m = client.post("/auth/login", json={"role": "mentor", "email": "m@example.com", "password": "password123"}).json()
    _submit(client, m)
    db = SessionLocal()
    try:
        admin.approve_mentor(db, "m@example.com", institution="Kerala Kalamandalam")
    finally:
        db.close()
    assert client.get("/teachers").json()[0]["institution"] == "Kerala Kalamandalam"


# ---------- mentor-only data ----------

def test_class_data_is_locked_until_the_mentor_is_verified(client):
    m = signup_mentor(client)
    other_teacher, _ = make_teacher()
    for path in ("stats", "bookings"):
        r = client.get(f"/teachers/{other_teacher}/{path}", headers=auth(m["token"]))
        assert r.status_code == 403, path


def test_verified_mentor_sees_only_their_own_classes(client):
    mentor, teacher_id = verified_mentor(client, slots=1)
    other_teacher, _ = make_teacher(name="Someone Else")

    assert client.get(f"/teachers/{teacher_id}/bookings", headers=auth(mentor["token"])).status_code == 200
    assert client.get(f"/teachers/{teacher_id}/stats", headers=auth(mentor["token"])).status_code == 200
    assert client.get(f"/teachers/{other_teacher}/bookings", headers=auth(mentor["token"])).status_code == 403
    assert client.get(f"/teachers/{other_teacher}/stats", headers=auth(mentor["token"])).status_code == 403


def test_parents_cannot_use_mentor_endpoints(client):
    _, teacher_id = verified_mentor(client)
    p = signup_parent(client)
    assert client.get(f"/teachers/{teacher_id}/bookings", headers=auth(p["token"])).status_code == 403
    assert client.get(f"/teachers/{teacher_id}/stats", headers=auth(p["token"])).status_code == 403


def test_mentor_sees_bookings_parents_make(client):
    mentor, teacher_id = verified_mentor(client, slots=2)
    p = signup_parent(client)
    child = add_child(client, p, name="Anjali")
    slot_id = client.get("/teachers").json()[0]["teacher_slots"][0]["id"]
    assert book(client, p, child, teacher_id, slot_id).status_code == 201

    (item,) = client.get(f"/teachers/{teacher_id}/bookings", headers=auth(mentor["token"])).json()
    assert item["children"]["name"] == "Anjali" and item["status"] == "confirmed"


# ---------- stats ----------

def test_stats_with_no_history(client):
    mentor, teacher_id = verified_mentor(client)
    r = client.get(f"/teachers/{teacher_id}/stats", headers=auth(mentor["token"]))
    assert r.json() == {"classes_this_week": 0, "active_students": 0, "attendance_rate": None}


def _insert_booking(teacher_id, parent_id, child_id, when, status="confirmed"):
    db = SessionLocal()
    try:
        slot = models.TeacherSlot(teacher_id=teacher_id, slot_time=when, is_booked=True)
        db.add(slot)
        db.flush()
        db.add(models.Booking(
            parent_id=parent_id, child_id=child_id, teacher_id=teacher_id,
            slot_id=slot.id, slot_time=when, status=status,
        ))
        db.commit()
    finally:
        db.close()


def test_stats_active_students_and_attendance_proxy(client):
    mentor, teacher_id = verified_mentor(client)
    p = signup_parent(client)
    c1, c2, c3 = (add_child(client, p, name=n) for n in ("A", "B", "C"))
    now = datetime.now(timezone.utc)
    # well away from "this week" so only the student/attendance logic is under test
    _insert_booking(teacher_id, p["id"], c1, now - timedelta(days=30))                       # past, attended
    _insert_booking(teacher_id, p["id"], c2, now - timedelta(days=31))                       # past, attended
    _insert_booking(teacher_id, p["id"], c3, now - timedelta(days=32), status="cancelled")   # past, cancelled
    _insert_booking(teacher_id, p["id"], c1, now + timedelta(days=60))                       # future: not "past"

    s = client.get(f"/teachers/{teacher_id}/stats", headers=auth(mentor["token"])).json()
    assert s["active_students"] == 2                       # c1, c2 (cancelled c3 excluded)
    assert s["classes_this_week"] == 0
    assert s["attendance_rate"] == pytest.approx(2 / 3 * 100)


def test_classes_this_week_uses_the_calendar_week_not_a_rolling_window(client):
    mentor, teacher_id = verified_mentor(client)
    p = signup_parent(client)
    child = add_child(client, p)
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    _insert_booking(teacher_id, p["id"], child, week_start + timedelta(seconds=1))          # this week
    _insert_booking(teacher_id, p["id"], child, week_start + timedelta(days=7, hours=1))    # next week
    _insert_booking(teacher_id, p["id"], child, week_start - timedelta(hours=1))            # last week
    _insert_booking(teacher_id, p["id"], child, week_start + timedelta(hours=2), status="cancelled")

    s = client.get(f"/teachers/{teacher_id}/stats", headers=auth(mentor["token"])).json()
    assert s["classes_this_week"] == 1
