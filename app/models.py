import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Boolean, ForeignKey, DateTime, Text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from .database import Base


def new_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class Teacher(Base):
    """A public, bookable teacher profile (what parents browse)."""
    __tablename__ = "teachers"
    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    name = Column(String, nullable=False)
    art_form = Column(String, nullable=False)
    bio = Column(Text)
    photo_url = Column(String)
    verified = Column(Boolean, default=True)
    institution = Column(String)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Named teacher_slots (not "slots") on purpose: the JSON key the Flutter
    # Teacher.fromMap reads is 'teacher_slots'.
    teacher_slots = relationship(
        "TeacherSlot", back_populates="teacher", cascade="all, delete-orphan"
    )


class TeacherSlot(Base):
    __tablename__ = "teacher_slots"
    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id", ondelete="CASCADE"))
    slot_time = Column(DateTime(timezone=True), nullable=False)
    is_booked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    teacher = relationship("Teacher", back_populates="teacher_slots")


class Parent(Base):
    __tablename__ = "parents"
    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    phone = Column(String)  # optional - the current app flow doesn't collect it
    consent_recording = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    children = relationship("Child", back_populates="parent", cascade="all, delete-orphan")


class Mentor(Base):
    """
    A mentor's account + application. Signing up creates the account
    ('pending'); submitting credential/experience/bio moves it to
    'under_review'; an admin linking it to a Teacher row makes it 'verified'
    and bookable. See verification_status.
    """
    __tablename__ = "mentors"
    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    phone = Column(String)
    art_form = Column(String, nullable=False)
    credential = Column(String)
    experience_years = Column(Integer)
    bio = Column(Text)
    profile_submitted_at = Column(DateTime(timezone=True))
    linked_teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    @property
    def verification_status(self) -> str:
        if self.linked_teacher_id:
            return "verified"
        if self.profile_submitted_at:
            return "under_review"
        return "pending"


class Child(Base):
    __tablename__ = "children"
    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    parent_id = Column(UUID(as_uuid=False), ForeignKey("parents.id", ondelete="CASCADE"))
    name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    art_form_interest = Column(String, nullable=False)
    level = Column(String, default="Beginner")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    parent = relationship("Parent", back_populates="children")


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    parent_id = Column(UUID(as_uuid=False), ForeignKey("parents.id", ondelete="CASCADE"))
    child_id = Column(UUID(as_uuid=False), ForeignKey("children.id", ondelete="CASCADE"))
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id", ondelete="CASCADE"))
    slot_id = Column(UUID(as_uuid=False), ForeignKey("teacher_slots.id", ondelete="CASCADE"))
    slot_time = Column(DateTime(timezone=True), nullable=False)
    video_link = Column(String)
    status = Column(String, default="confirmed")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    child = relationship("Child")
    teacher = relationship("Teacher")
