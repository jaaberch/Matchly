"""Venue, field and camera payloads."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from matchly_shared.domain import CameraStatus, VenueRole

from .common import ORMModel


# ── Venue ────────────────────────────────────────────────────────────────
class VenueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160, examples=["Arena Demo Casablanca"])
    location: str = Field(min_length=1, max_length=255)
    timezone: str = Field(default="Africa/Casablanca", max_length=64)
    video_retention_days: int | None = Field(default=None, ge=1, le=3650)
    recording_disclosure: str | None = None


class VenueUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    location: str | None = Field(default=None, min_length=1, max_length=255)
    timezone: str | None = Field(default=None, max_length=64)
    video_retention_days: int | None = Field(default=None, ge=1, le=3650)
    recording_disclosure: str | None = None


class VenueOut(ORMModel):
    id: uuid.UUID
    name: str
    location: str
    timezone: str
    video_retention_days: int
    recording_disclosure: str | None
    created_at: dt.datetime


# ── Camera ───────────────────────────────────────────────────────────────
class CameraOut(ORMModel):
    """Camera as seen by venue staff. Never carries the RTSP URL or the token."""

    id: uuid.UUID
    field_id: uuid.UUID
    name: str
    status: CameraStatus
    last_seen: dt.datetime | None
    online: bool = Field(
        description="Derived from the heartbeat, not stored: last_seen within "
        "CAMERA_OFFLINE_AFTER_SECONDS."
    )


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["Pitch 1 — wide 4K"])
    stream_url: str | None = Field(default=None, max_length=2048)


class CameraCreated(BaseModel):
    """Returned once, when a camera is attached.

    ``token`` is the capture agent's credential and is shown exactly once — it is
    stored hashed, so it cannot be recovered later. Re-attaching the camera issues
    a new one.
    """

    camera: CameraOut
    token: str


class CameraStatusOut(BaseModel):
    id: uuid.UUID
    field_id: uuid.UUID
    name: str
    status: CameraStatus
    last_seen: dt.datetime | None
    online: bool
    current_match_id: uuid.UUID | None = None


class CameraHeartbeatIn(BaseModel):
    status: CameraStatus = CameraStatus.ONLINE
    note: str | None = Field(default=None, max_length=500)


# ── Field ────────────────────────────────────────────────────────────────
class FieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["Pitch 1"])


class FieldOut(ORMModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    name: str
    created_at: dt.datetime
    #: Mirrors the agreed model's `Field.camera_id`; the stored edge is
    #: `cameras.field_id` (see ARCHITECTURE.md section 4.2).
    camera_id: uuid.UUID | None = None
    camera: CameraOut | None = None


class VenueDetail(VenueOut):
    fields: list[FieldOut] = []


# ── Membership ───────────────────────────────────────────────────────────
class VenueMemberCreate(BaseModel):
    phone: str = Field(
        min_length=6,
        max_length=24,
        description="Phone of the operator to grant access to. The account is "
        "created if it does not exist yet.",
    )
    name: str | None = Field(default=None, max_length=120)
    role: VenueRole = VenueRole.OPERATOR


class VenueMemberOut(BaseModel):
    id: uuid.UUID
    venue_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    role: VenueRole
    created_at: dt.datetime
