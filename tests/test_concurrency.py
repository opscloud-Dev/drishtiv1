import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal
from app.main import app
from .helpers import add_child, book, make_teacher, signup_parent

N_PARENTS = 8


def test_simultaneous_bookings_of_one_slot_produce_exactly_one_winner(client):
    parents = [signup_parent(client, email=f"p{i}@example.com") for i in range(N_PARENTS)]
    children = [add_child(client, p) for p in parents]
    teacher_id, (slot_id,) = make_teacher()

    barrier = threading.Barrier(N_PARENTS)

    def attempt(i: int) -> int:
        with TestClient(app) as c:      # one client per thread
            barrier.wait()              # release everyone at the same moment
            return book(c, parents[i], children[i], teacher_id, slot_id).status_code

    with ThreadPoolExecutor(max_workers=N_PARENTS) as pool:
        codes = list(pool.map(attempt, range(N_PARENTS)))

    assert sorted(codes) == [201] + [409] * (N_PARENTS - 1), codes

    db = SessionLocal()
    try:
        assert db.query(models.Booking).filter_by(slot_id=slot_id).count() == 1
    finally:
        db.close()
