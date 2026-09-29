from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from . import models, schemas
from .auth import (
    DUMMY_HASH,
    Principal,
    create_token,
    hash_password,
    require_mentor,
    require_parent,
    verify_password,
)
from .database import Base, engine, get_db


def check_schema_current() -> None:
    """
    create_all() never alters existing tables, so a database created by an
    older version of this app would fail later with confusing 500 errors.
    Detect that at startup and say exactly what to do instead.
    """
    tables = set(inspect(engine).get_table_names())
    expected = {
        "parents": "password_hash",
        "mentors": "profile_submitted_at",
    }
    for table, column in expected.items():
        if table in tables:
            cols = {c["name"] for c in inspect(engine).get_columns(table)}
            if column not in cols:
                raise RuntimeError(
                    f"Your database was created by an older version of Drishti "
                    f"(table '{table}' has no '{column}' column).\n"
                    f"Reset it with:  python -m app.reset_db\n"
                    f"(This deletes all existing data, then reseeds the sample teachers.)"
                )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    check_schema_current()
    Base.metadata.create_all(bind=engine)  # the Python equivalent of schema.sql
    yield


app = FastAPI(title="Drishti API", lifespan=lifespan)

# Open CORS is fine for a native mobile client (which ignores CORS anyway) and
# for testing; narrow it if you ever add a browser front end.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def video_link_for(booking_id: str) -> str:
    # Placeholder - no real video integration yet.
    return f"https://meet.drishti.ai/mock/{booking_id}"


def _auth_out(user, role: str) -> schemas.AuthOut:
    return schemas.AuthOut(
        token=create_token(user.id, role), role=role, id=user.id, name=user.name
    )


def _ensure_self(principal: Principal, claimed_id: UUID | str) -> None:
    if str(claimed_id) != principal.id:
        raise HTTPException(403, "You can only access your own account")


# =====================================================================
# Auth
# =====================================================================

@app.post("/auth/signup/parent", response_model=schemas.AuthOut, status_code=201)
def signup_parent(req: schemas.ParentSignupRequest, db: Session = Depends(get_db)):
    if db.query(models.Parent).filter_by(email=req.email).first():
        raise HTTPException(
            409, "An account with this email already exists. Try signing in instead."
        )
    parent = models.Parent(
        name=req.name, email=req.email, password_hash=hash_password(req.password)
    )
    db.add(parent)
    try:
        db.commit()
    except IntegrityError:  # two signups with the same email at the same instant
        db.rollback()
        raise HTTPException(
            409, "An account with this email already exists. Try signing in instead."
        )
    return _auth_out(parent, "parent")


@app.post("/auth/signup/mentor", response_model=schemas.AuthOut, status_code=201)
def signup_mentor(req: schemas.MentorSignupRequest, db: Session = Depends(get_db)):
    if db.query(models.Mentor).filter_by(email=req.email).first():
        raise HTTPException(
            409, "An account with this email already exists. Try signing in instead."
        )
    mentor = models.Mentor(
        name=req.name,
        email=req.email,
        password_hash=hash_password(req.password),
        art_form=req.art_form,
    )
    db.add(mentor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "An account with this email already exists. Try signing in instead."
        )
    return _auth_out(mentor, "mentor")


@app.post("/auth/login", response_model=schemas.AuthOut)
def login(req: schemas.LoginRequest, db: Session = Depends(get_db)):
    model = models.Parent if req.role == "parent" else models.Mentor
    user = db.query(model).filter_by(email=req.email).first()
    # Always run one bcrypt check so a missing account and a wrong password
    # look identical (same message, same timing).
    password_ok = verify_password(req.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not password_ok:
        raise HTTPException(401, "Incorrect email or password")
    return _auth_out(user, req.role)


# =====================================================================
# Parents & children
# =====================================================================

@app.get("/parents/{parent_id}/children", response_model=list[schemas.ChildOut])
def list_children(
    parent_id: UUID,
    principal: Principal = Depends(require_parent),
    db: Session = Depends(get_db),
):
    _ensure_self(principal, parent_id)
    return (
        db.query(models.Child)
        .filter_by(parent_id=principal.id)
        .order_by(models.Child.created_at)
        .all()
    )


@app.post("/children", response_model=schemas.IdResponse, status_code=201)
def add_child(
    req: schemas.ChildCreateRequest,
    principal: Principal = Depends(require_parent),
    db: Session = Depends(get_db),
):
    _ensure_self(principal, req.parent_id)
    child = models.Child(
        parent_id=principal.id,
        name=req.name,
        age=req.age,
        art_form_interest=req.art_form_interest,
        level=req.level,
    )
    db.add(child)
    db.commit()
    return schemas.IdResponse(id=child.id)


# =====================================================================
# Mentors
# =====================================================================

@app.get("/mentors/{mentor_id}", response_model=schemas.MentorOut)
def get_mentor(mentor_id: UUID, principal: Principal = Depends(require_mentor)):
    _ensure_self(principal, mentor_id)
    return principal.user


@app.put("/mentors/{mentor_id}/profile", response_model=schemas.MentorOut)
def submit_mentor_profile(
    mentor_id: UUID,
    req: schemas.MentorProfileSubmit,
    principal: Principal = Depends(require_mentor),
    db: Session = Depends(get_db),
):
    """'Submit for review'. Safe to call again to update the submission."""
    _ensure_self(principal, mentor_id)
    mentor = principal.user
    mentor.credential = req.credential
    mentor.experience_years = req.experience_years
    mentor.bio = req.bio
    mentor.profile_submitted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(mentor)
    return mentor


def _require_own_teacher(principal: Principal, teacher_id: UUID) -> None:
    """Only the mentor linked (verified) to this teacher may see its data."""
    linked = principal.user.linked_teacher_id
    if not linked or linked != str(teacher_id):
        raise HTTPException(403, "You can only view your own classes")


# =====================================================================
# Teachers
# =====================================================================

@app.get("/teachers", response_model=list[schemas.TeacherOut])
def list_teachers(db: Session = Depends(get_db)):
    """Public directory. Only open, upcoming slots are included."""
    now = datetime.now(timezone.utc)
    teachers = (
        db.query(models.Teacher)
        .options(joinedload(models.Teacher.teacher_slots))
        .order_by(models.Teacher.name)
        .all()
    )
    out = []
    for t in teachers:
        open_slots = sorted(
            (s for s in t.teacher_slots if not s.is_booked and s.slot_time > now),
            key=lambda s: s.slot_time,
        )
        out.append(
            schemas.TeacherOut(
                id=t.id,
                name=t.name,
                art_form=t.art_form,
                bio=t.bio,
                photo_url=t.photo_url,
                verified=bool(t.verified),
                institution=t.institution,
                teacher_slots=[schemas.TeacherSlotOut.model_validate(s) for s in open_slots],
            )
        )
    return out


@app.get("/teachers/{teacher_id}/stats", response_model=schemas.MentorStatsOut)
def teacher_stats(
    teacher_id: UUID,
    principal: Principal = Depends(require_mentor),
    db: Session = Depends(get_db),
):
    _require_own_teacher(principal, teacher_id)
    bookings = db.query(models.Booking).filter_by(teacher_id=str(teacher_id)).all()
    active = [b for b in bookings if b.status != "cancelled"]

    # "This week" = the calendar week, Monday 00:00 to next Monday 00:00 (UTC).
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end = week_start + timedelta(days=7)
    this_week = [b for b in active if week_start <= b.slot_time < week_end]

    # There is no real attendance tracking yet. As a stand-in we report the
    # share of *past* scheduled classes that were not cancelled - and null
    # (shown as a dash in the app) until there is any history at all.
    past = [b for b in bookings if b.slot_time < now]
    rate = None
    if past:
        rate = len([b for b in past if b.status != "cancelled"]) / len(past) * 100

    return schemas.MentorStatsOut(
        classes_this_week=len(this_week),
        active_students=len({b.child_id for b in active}),
        attendance_rate=rate,
    )


def _booking_list_item(b: models.Booking) -> schemas.BookingListItemOut:
    return schemas.BookingListItemOut(
        id=b.id,
        slot_id=b.slot_id,
        slot_time=b.slot_time,
        video_link=b.video_link,
        status=b.status,
        children=schemas.NestedName(name=b.child.name if b.child else ""),
        teachers=schemas.NestedTeacherInfo(
            name=b.teacher.name if b.teacher else "",
            art_form=b.teacher.art_form if b.teacher else "",
        ),
    )


@app.get("/teachers/{teacher_id}/bookings", response_model=list[schemas.BookingListItemOut])
def teacher_bookings(
    teacher_id: UUID,
    principal: Principal = Depends(require_mentor),
    db: Session = Depends(get_db),
):
    _require_own_teacher(principal, teacher_id)
    bookings = (
        db.query(models.Booking)
        .options(joinedload(models.Booking.child), joinedload(models.Booking.teacher))
        .filter_by(teacher_id=str(teacher_id))
        .order_by(models.Booking.slot_time)
        .all()
    )
    return [_booking_list_item(b) for b in bookings]


# =====================================================================
# Bookings
# =====================================================================

@app.post("/bookings", response_model=schemas.BookingCreatedOut, status_code=201)
def create_booking(
    req: schemas.BookingCreateRequest,
    principal: Principal = Depends(require_parent),
    db: Session = Depends(get_db),
):
    _ensure_self(principal, req.parent_id)

    child = db.get(models.Child, req.child_id)
    if child is None or child.parent_id != principal.id:
        raise HTTPException(403, "That child isn't on your account")

    # Row lock: if two parents tap the same slot at once, the second one waits
    # here, then sees is_booked=True and gets a clean 409 instead of a
    # double booking.
    slot = (
        db.query(models.TeacherSlot).filter_by(id=req.slot_id).with_for_update().first()
    )
    if slot is None:
        raise HTTPException(404, "That time slot no longer exists")
    if slot.teacher_id != req.teacher_id:
        raise HTTPException(400, "That slot doesn't belong to this teacher")
    if slot.is_booked:
        raise HTTPException(409, "Sorry, that slot was just booked. Please pick another.")
    if slot.slot_time <= datetime.now(timezone.utc):
        raise HTTPException(400, "That time has already passed")

    slot.is_booked = True
    booking = models.Booking(
        parent_id=principal.id,
        child_id=child.id,
        teacher_id=slot.teacher_id,
        slot_id=slot.id,
        slot_time=slot.slot_time,
    )
    db.add(booking)
    db.flush()  # assigns booking.id
    booking.video_link = video_link_for(booking.id)
    db.commit()
    return schemas.BookingCreatedOut(id=booking.id, video_link=booking.video_link)


@app.get("/parents/{parent_id}/bookings", response_model=list[schemas.BookingListItemOut])
def parent_bookings(
    parent_id: UUID,
    principal: Principal = Depends(require_parent),
    db: Session = Depends(get_db),
):
    _ensure_self(principal, parent_id)
    bookings = (
        db.query(models.Booking)
        .options(joinedload(models.Booking.child), joinedload(models.Booking.teacher))
        .filter_by(parent_id=principal.id)
        .order_by(models.Booking.slot_time)
        .all()
    )
    return [_booking_list_item(b) for b in bookings]


@app.patch("/bookings/{booking_id}/cancel")
def cancel_booking(
    booking_id: UUID,
    principal: Principal = Depends(require_parent),
    db: Session = Depends(get_db),
):
    booking = (
        db.query(models.Booking)
        .filter_by(id=str(booking_id))
        .with_for_update()
        .first()
    )
    # 404 (not 403) for someone else's booking, so ids can't be probed.
    if booking is None or booking.parent_id != principal.id:
        raise HTTPException(404, "Booking not found")

    # Only free the slot on the first cancellation. Cancelling twice must not
    # re-open a slot another family has since booked.
    if booking.status == "confirmed":
        booking.status = "cancelled"
        slot = (
            db.query(models.TeacherSlot)
            .filter_by(id=booking.slot_id)
            .with_for_update()
            .first()
        )
        if slot is not None:
            slot.is_booked = False
        db.commit()
    return {"ok": True}


@app.get("/health")
def health():
    return {"status": "ok"}
