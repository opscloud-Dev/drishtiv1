from datetime import datetime
from typing import Optional, List, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# The fixed product lists. The Flutter dropdowns use exactly these strings and
# the Programs screen filters teachers by exact match, so we validate them
# here instead of letting free-text drift break the filter.
ART_FORMS = ["Bharatanatyam", "Mohiniyattam", "Kathakali", "Carnatic Music", "Percussion"]
LEVELS = ["Beginner", "Intermediate", "Advanced"]

MIN_PASSWORD_LEN = 8
MAX_PASSWORD_BYTES = 72  # bcrypt ignores everything past 72 bytes


def _check_password(v: str) -> str:
    if len(v) < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters")
    if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("Password is too long (max 72 bytes)")
    return v


def _uuid_str(v: str) -> str:
    """Normalise to canonical lowercase UUID text, or reject as invalid."""
    try:
        return str(UUID(str(v)))
    except ValueError:
        raise ValueError("Invalid id")


def _clean_name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Name is required")
    return v


# ---------------- Requests ----------------

class ParentSignupRequest(BaseModel):
    name: str = Field(max_length=100)
    email: EmailStr
    password: str

    _name = field_validator("name")(_clean_name)
    _password = field_validator("password")(_check_password)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.strip().lower()


class MentorSignupRequest(BaseModel):
    name: str = Field(max_length=100)
    email: EmailStr
    password: str
    art_form: str

    _name = field_validator("name")(_clean_name)
    _password = field_validator("password")(_check_password)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("art_form")
    @classmethod
    def _art_form(cls, v: str) -> str:
        if v not in ART_FORMS:
            raise ValueError(f"Art form must be one of: {', '.join(ART_FORMS)}")
        return v


class LoginRequest(BaseModel):
    role: Literal["parent", "mentor"]
    email: EmailStr
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.strip().lower()


class MentorProfileSubmit(BaseModel):
    credential: str = Field(min_length=2, max_length=200)
    experience_years: int = Field(ge=0, le=60)
    bio: str = Field(min_length=1, max_length=2000)

    @field_validator("credential", "bio")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("This field can't be blank")
        return v


class ChildCreateRequest(BaseModel):
    parent_id: str
    name: str = Field(max_length=100)
    age: int = Field(ge=1, le=18)
    art_form_interest: str
    level: str = "Beginner"

    _name = field_validator("name")(_clean_name)
    _parent_id = field_validator("parent_id")(_uuid_str)

    @field_validator("art_form_interest")
    @classmethod
    def _art_form(cls, v: str) -> str:
        if v not in ART_FORMS:
            raise ValueError(f"Art form must be one of: {', '.join(ART_FORMS)}")
        return v

    @field_validator("level")
    @classmethod
    def _level(cls, v: str) -> str:
        if v not in LEVELS:
            raise ValueError(f"Level must be one of: {', '.join(LEVELS)}")
        return v


class BookingCreateRequest(BaseModel):
    parent_id: str
    child_id: str
    teacher_id: str
    slot_id: str

    _ids = field_validator("parent_id", "child_id", "teacher_id", "slot_id")(_uuid_str)


# ---------------- Responses ----------------
# Field names/shapes match exactly what the Flutter model classes
# (Teacher.fromMap, Child.fromMap, BookingListItem.fromMap, Mentor.fromMap)
# expect.

class AuthOut(BaseModel):
    token: str
    role: str
    id: str
    name: str


class IdResponse(BaseModel):
    id: str


class TeacherSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    teacher_id: str
    slot_time: datetime
    is_booked: bool


class TeacherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    art_form: str
    bio: Optional[str] = None
    photo_url: Optional[str] = None
    verified: bool
    institution: Optional[str] = None
    teacher_slots: List[TeacherSlotOut] = []


class ChildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    parent_id: str
    name: str
    age: int
    art_form_interest: str
    level: str


class MentorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    phone: Optional[str] = None
    email: str
    art_form: str
    credential: Optional[str] = None
    experience_years: Optional[int] = None
    bio: Optional[str] = None
    linked_teacher_id: Optional[str] = None
    # 'pending' | 'under_review' | 'verified'
    verification_status: str


class MentorStatsOut(BaseModel):
    classes_this_week: int
    active_students: int
    attendance_rate: Optional[float] = None


class BookingCreatedOut(BaseModel):
    id: str
    video_link: str


class NestedName(BaseModel):
    name: str


class NestedTeacherInfo(BaseModel):
    name: str
    art_form: str


class BookingListItemOut(BaseModel):
    id: str
    slot_id: str
    slot_time: datetime
    video_link: Optional[str] = None
    status: str
    children: NestedName
    teachers: NestedTeacherInfo
