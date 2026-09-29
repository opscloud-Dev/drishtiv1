from datetime import datetime, timedelta, timezone

from app import models
from app.database import SessionLocal
from .helpers import add_child, auth, book, make_teacher, signup_parent


# ---------- children ----------

def test_add_and_list_children(client):
    p = signup_parent(client)
    add_child(client, p, name="Anjali", age=8, level="Beginner")
    add_child(client, p, name="Kiran", age=10, art="Carnatic Music", level="Advanced")
    r = client.get(f"/parents/{p['id']}/children", headers=auth(p["token"]))
    assert r.status_code == 200
    assert [c["name"] for c in r.json()] == ["Anjali", "Kiran"]
    assert set(r.json()[0]) == {"id", "parent_id", "name", "age", "art_form_interest", "level"}


def test_child_validation(client):
    p = signup_parent(client)
    base = {"parent_id": p["id"], "name": "A", "age": 8, "art_form_interest": "Kathakali", "level": "Beginner"}
    for bad in (
        {"age": 0}, {"age": 30}, {"level": "Wizard"}, {"art_form_interest": "Juggling"}, {"name": "  "},
    ):
        r = client.post("/children", headers=auth(p["token"]), json={**base, **bad})
        assert r.status_code == 422, bad


def test_parent_cannot_read_or_write_another_parents_data(client):
    a = signup_parent(client, email="a@example.com")
    b = signup_parent(client, email="b@example.com")
    add_child(client, a)
    # read
    assert client.get(f"/parents/{a['id']}/children", headers=auth(b["token"])).status_code == 403
    assert client.get(f"/parents/{a['id']}/bookings", headers=auth(b["token"])).status_code == 403
    # write: claim to be A while holding B's token
    r = client.post(
        "/children", headers=auth(b["token"]),
        json={"parent_id": a["id"], "name": "Sneaky", "age": 5, "art_form_interest": "Kathakali"},
    )
    assert r.status_code == 403


def test_malformed_id_in_path_is_a_clean_422(client):
    p = signup_parent(client)
    assert client.get("/parents/not-a-uuid/children", headers=auth(p["token"])).status_code == 422


# ---------- teachers (public directory) ----------

def test_teacher_directory_is_public_and_lists_only_open_future_slots(client):
    teacher_id, (future, booked, past) = make_teacher(slot_offsets_hours=(24, 48, -24))
    db = SessionLocal()
    try:
        db.get(models.TeacherSlot, booked).is_booked = True
        db.commit()
    finally:
        db.close()

    r = client.get("/teachers")  # no token needed
    assert r.status_code == 200
    (t,) = r.json()
    assert t["id"] == teacher_id
    assert [s["id"] for s in t["teacher_slots"]] == [future]
    assert set(t) >= {"id", "name", "art_form", "bio", "verified", "institution", "teacher_slots"}


# ---------- booking ----------

def test_booking_flow(client):
    p = signup_parent(client)
    child = add_child(client, p, name="Anjali")
    teacher_id, (slot_id,) = make_teacher()

    r = book(client, p, child, teacher_id, slot_id)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["video_link"].endswith(body["id"])

    # the slot is gone from the public directory
    assert client.get("/teachers").json()[0]["teacher_slots"] == []

    # and the parent sees it, in exactly the nested shape the Flutter model reads
    (item,) = client.get(f"/parents/{p['id']}/bookings", headers=auth(p["token"])).json()
    assert item["status"] == "confirmed"
    assert item["children"] == {"name": "Anjali"}
    assert item["teachers"] == {"name": "Lakshmi Menon", "art_form": "Mohiniyattam"}
    assert item["slot_id"] == slot_id


def test_same_slot_cannot_be_booked_twice(client):
    a = signup_parent(client, email="a@example.com")
    b = signup_parent(client, email="b@example.com")
    ca, cb = add_child(client, a), add_child(client, b)
    teacher_id, (slot_id,) = make_teacher()

    assert book(client, a, ca, teacher_id, slot_id).status_code == 201
    second = book(client, b, cb, teacher_id, slot_id)
    assert second.status_code == 409
    assert "just booked" in second.json()["detail"]


def test_cannot_book_for_someone_elses_child(client):
    a = signup_parent(client, email="a@example.com")
    b = signup_parent(client, email="b@example.com")
    a_child = add_child(client, a)
    teacher_id, (slot_id,) = make_teacher()
    assert book(client, b, a_child, teacher_id, slot_id).status_code == 403


def test_slot_must_belong_to_the_named_teacher(client):
    p = signup_parent(client)
    child = add_child(client, p)
    _, (slot_id,) = make_teacher(name="One")
    other_teacher, _ = make_teacher(name="Two")
    assert book(client, p, child, other_teacher, slot_id).status_code == 400


def test_cannot_book_a_slot_in_the_past(client):
    p = signup_parent(client)
    child = add_child(client, p)
    teacher_id, (slot_id,) = make_teacher(slot_offsets_hours=(-2,))
    assert book(client, p, child, teacher_id, slot_id).status_code == 400


def test_booking_needs_a_parent_login(client):
    p = signup_parent(client)
    child = add_child(client, p)
    teacher_id, (slot_id,) = make_teacher()
    r = client.post(
        "/bookings",
        json={"parent_id": p["id"], "child_id": child, "teacher_id": teacher_id, "slot_id": slot_id},
    )
    assert r.status_code == 401


# ---------- cancelling ----------

def test_cancel_reopens_the_slot(client):
    p = signup_parent(client)
    child = add_child(client, p)
    teacher_id, (slot_id,) = make_teacher()
    booking_id = book(client, p, child, teacher_id, slot_id).json()["id"]

    r = client.patch(f"/bookings/{booking_id}/cancel", headers=auth(p["token"]))
    assert r.status_code == 200
    assert [s["id"] for s in client.get("/teachers").json()[0]["teacher_slots"]] == [slot_id]
    (item,) = client.get(f"/parents/{p['id']}/bookings", headers=auth(p["token"])).json()
    assert item["status"] == "cancelled"


def test_cancelling_twice_does_not_reopen_a_slot_someone_else_now_holds(client):
    a = signup_parent(client, email="a@example.com")
    b = signup_parent(client, email="b@example.com")
    ca, cb = add_child(client, a), add_child(client, b)
    teacher_id, (slot_id,) = make_teacher()

    a_booking = book(client, a, ca, teacher_id, slot_id).json()["id"]
    client.patch(f"/bookings/{a_booking}/cancel", headers=auth(a["token"]))
    assert book(client, b, cb, teacher_id, slot_id).status_code == 201  # B takes the freed slot

    # A cancels the same booking again - must be a no-op, not a double-booking
    assert client.patch(f"/bookings/{a_booking}/cancel", headers=auth(a["token"])).status_code == 200
    db = SessionLocal()
    try:
        assert db.get(models.TeacherSlot, slot_id).is_booked is True
    finally:
        db.close()


def test_cannot_cancel_someone_elses_booking(client):
    a = signup_parent(client, email="a@example.com")
    b = signup_parent(client, email="b@example.com")
    teacher_id, (slot_id,) = make_teacher()
    booking_id = book(client, a, add_child(client, a), teacher_id, slot_id).json()["id"]
    assert client.patch(f"/bookings/{booking_id}/cancel", headers=auth(b["token"])).status_code == 404
    # ...and A's booking is untouched
    (item,) = client.get(f"/parents/{a['id']}/bookings", headers=auth(a["token"])).json()
    assert item["status"] == "confirmed"
