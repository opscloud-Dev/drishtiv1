"""
Admin tasks you'd otherwise do by hand in SQL.

    python -m app.admin list-mentors
    python -m app.admin approve-mentor EMAIL [--slots N] [--institution TEXT] [--force]
    python -m app.admin set-password ROLE EMAIL        (ROLE = parent or mentor)

approve-mentor  Verifies a mentor: creates their public, bookable Teacher
                profile from what they submitted and links it. After this the
                mentor's app switches from "Under review" to their real
                dashboard, and parents can find and book them.
                --slots N adds N placeholder daily slots (10:00 UTC, starting
                tomorrow) so the mentor is bookable straight away - edit real
                times in the teacher_slots table afterwards.
set-password    There is no "forgot password" email flow yet, so this is how you
                reset a tester's password. It prompts for the new password.
"""
import argparse
import getpass
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import models
from .auth import hash_password
from .database import SessionLocal
from .schemas import MIN_PASSWORD_LEN


class AdminError(Exception):
    """A problem the admin can fix - shown as a plain message, not a traceback."""


def _find_mentor(db: Session, email: str) -> models.Mentor:
    mentor = db.query(models.Mentor).filter_by(email=email.strip().lower()).first()
    if mentor is None:
        raise AdminError(f"No mentor with email '{email}'.")
    return mentor


def list_mentors(db: Session) -> list[tuple[str, str, str, str]]:
    rows = []
    for m in db.query(models.Mentor).order_by(models.Mentor.created_at).all():
        rows.append((m.email, m.name, m.art_form, m.verification_status))
    return rows


def approve_mentor(
    db: Session,
    email: str,
    slots: int = 0,
    institution: str | None = None,
    force: bool = False,
) -> models.Teacher:
    mentor = _find_mentor(db, email)
    if mentor.linked_teacher_id:
        raise AdminError(f"{mentor.email} is already verified.")
    if not mentor.profile_submitted_at and not force:
        raise AdminError(
            f"{mentor.email} hasn't submitted their credential, experience and "
            f"bio yet. Approve anyway with --force."
        )

    teacher = models.Teacher(
        name=mentor.name,
        art_form=mentor.art_form,
        bio=mentor.bio,
        institution=institution or mentor.credential,
        verified=True,
    )
    db.add(teacher)
    db.flush()  # assigns teacher.id
    mentor.linked_teacher_id = teacher.id

    first_day = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    for i in range(slots):
        db.add(models.TeacherSlot(teacher_id=teacher.id, slot_time=first_day + timedelta(days=i)))

    db.commit()
    return teacher


def set_password(db: Session, role: str, email: str, new_password: str) -> None:
    if role not in ("parent", "mentor"):
        raise AdminError("Role must be 'parent' or 'mentor'.")
    if len(new_password) < MIN_PASSWORD_LEN:
        raise AdminError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if len(new_password.encode("utf-8")) > 72:
        raise AdminError("Password is too long (max 72 bytes).")
    model = models.Parent if role == "parent" else models.Mentor
    user = db.query(model).filter_by(email=email.strip().lower()).first()
    if user is None:
        raise AdminError(f"No {role} with email '{email}'.")
    user.password_hash = hash_password(new_password)
    db.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drishti admin tasks")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-mentors", help="show every mentor and their status")

    ap = sub.add_parser("approve-mentor", help="verify a mentor and make them bookable")
    ap.add_argument("email")
    ap.add_argument("--slots", type=int, default=0, help="add N placeholder daily slots")
    ap.add_argument("--institution", help="text for the green 'verified' badge parents see")
    ap.add_argument("--force", action="store_true", help="approve even if profile not submitted")

    sp = sub.add_parser("set-password", help="reset a user's password")
    sp.add_argument("role", choices=["parent", "mentor"])
    sp.add_argument("email")

    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        if args.cmd == "list-mentors":
            rows = list_mentors(db)
            if not rows:
                print("No mentors yet.")
            for email, name, art, status in rows:
                print(f"{status:<13} {email:<32} {name} ({art})")
        elif args.cmd == "approve-mentor":
            teacher = approve_mentor(db, args.email, args.slots, args.institution, args.force)
            print(f"Verified {args.email}. Teacher profile id: {teacher.id}")
            if args.slots:
                print(f"Added {args.slots} placeholder slot(s) - edit teacher_slots for real times.")
        elif args.cmd == "set-password":
            pw = getpass.getpass("New password: ")
            if pw != getpass.getpass("Repeat it: "):
                raise AdminError("Passwords didn't match.")
            set_password(db, args.role, args.email, pw)
            print("Password updated.")
    except AdminError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
