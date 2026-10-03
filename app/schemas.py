"""Request/response models for the API."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class OpenSessionIn(BaseModel):
    slot_id: int
    #: ISO date; defaults to today. Explicit so a teacher can mark a period they missed
    #: yesterday, within the edit window.
    date: Optional[str] = None


class MarkIn(BaseModel):
    user_id: int
    status: str


class MarkBatchIn(BaseModel):
    """One save = the whole register. Sending the full roster rather than a delta means a
    dropped connection cannot leave half the class marked."""

    marks: List[MarkIn] = Field(min_length=1, max_length=500)


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    role: str
    user_id: int
    display_name: str


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    email: Optional[str] = None
    roll_number: Optional[str] = None


class UserCreateIn(RegisterIn):
    role: str = "student"


class ConsentIn(BaseModel):
    consent_given: bool
    consent_text_version: str = "v1"


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    roll_number: Optional[str] = None
    email: Optional[str] = None
    consent_given: bool
    has_biometrics: bool


class CameraIn(BaseModel):
    name: str
    room: str
    source: str
    mode: str = "kiosk"


class CameraOut(BaseModel):
    id: int
    name: str
    room: str
    source: str
    mode: str
    status: str
    status_detail: Optional[str] = None
    last_heartbeat: Optional[datetime] = None
    measured_fps: float = 0.0
    running: bool = False


class SessionIn(BaseModel):
    title: str
    room: str
    scheduled_start: datetime
    scheduled_end: datetime
    camera_id: Optional[int] = None
    mode: Optional[str] = None
    grace_minutes: Optional[int] = None
    min_presence_seconds: Optional[int] = None


class SessionOut(BaseModel):
    id: int
    title: str
    room: str
    camera_id: Optional[int]
    owner_id: int
    scheduled_start: datetime
    scheduled_end: datetime
    mode: str
    grace_minutes: int
    min_presence_seconds: int


class RosterIn(BaseModel):
    user_ids: List[int]


class OverrideIn(BaseModel):
    status: str
    reason: str = Field(min_length=3, max_length=300,
                        description="Required. Written to the audit log.")


class AssignUnknownIn(BaseModel):
    user_id: int
    reason: str = Field(min_length=3, max_length=300)


class CorrectionIn(BaseModel):
    session_id: int
    message: str = Field(min_length=3, max_length=2000)
