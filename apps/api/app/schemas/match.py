"""Match, check-in and roster payloads."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field, model_validator

from matchly_shared.domain import MatchStatus, Team, VideoStatus

from .common import ORMModel

JerseyNumber = Field(ge=0, le=99, description="0–99, unique per team unless overridden.")


# ── Creation and editing ─────────────────────────────────────────────────
class MatchCreate(BaseModel):
    field_id: uuid.UUID
    starts_at: dt.datetime
    ends_at: dt.datetime
    title: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _check_window(self) -> MatchCreate:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if (self.ends_at - self.starts_at) > dt.timedelta(hours=6):
            raise ValueError("a match cannot be longer than 6 hours")
        return self


class MatchUpdate(BaseModel):
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None
    title: str | None = Field(default=None, max_length=160)


# ── Nested references ────────────────────────────────────────────────────
class VenueRef(BaseModel):
    id: uuid.UUID
    name: str
    location: str


class FieldRef(BaseModel):
    id: uuid.UUID
    name: str


class MatchPlayerOut(BaseModel):
    """A player on the roster.

    Carries the name only. Phone numbers are never exposed to other players —
    the roster is visible to everyone in the match.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    avatar: str | None = None
    team: Team
    jersey_number: int
    jersey_override: bool = False
    is_me: bool = False


class VideoRef(BaseModel):
    id: uuid.UUID
    status: VideoStatus
    duration: float | None = None


# ── Responses ────────────────────────────────────────────────────────────
class MatchSummary(BaseModel):
    id: uuid.UUID
    title: str | None
    status: MatchStatus
    starts_at: dt.datetime
    ends_at: dt.datetime
    join_code: str
    venue: VenueRef
    field: FieldRef
    player_count: int
    highlight_count: int
    #: Derived from the video row: the processed replay when there is one, else
    #: the master. Never a second stored column.
    video_url: str | None = None


class MatchDetail(MatchSummary):
    players: list[MatchPlayerOut] = []
    video: VideoRef | None = None
    created_at: dt.datetime


# ── Check-in ─────────────────────────────────────────────────────────────
class MatchJoinPreview(BaseModel):
    """What a player sees after scanning the QR code, before signing in.

    Public, so it deliberately carries no player identities — only which numbers
    are already taken, which is all that is needed to pick one.
    """

    match_id: uuid.UUID
    title: str | None
    status: MatchStatus
    starts_at: dt.datetime
    ends_at: dt.datetime
    venue_name: str
    field_name: str
    recording_disclosure: str | None
    joinable: bool
    taken_jerseys: dict[Team, list[int]]
    team_sizes: dict[Team, int]
    #: Only meaningful for an authenticated caller.
    already_joined: bool = False
    my_team: Team | None = None
    my_jersey_number: int | None = None


class MatchJoinIn(BaseModel):
    team: Team
    jersey_number: int = JerseyNumber
    consent: bool = Field(description="Participation consent. Check-in cannot complete without it.")


class MatchPlayerUpdate(BaseModel):
    """Operator edit of a roster entry."""

    team: Team | None = None
    jersey_number: int | None = Field(default=None, ge=0, le=99)
    allow_duplicate_jersey: bool = Field(
        default=False,
        description="Administrator override: permits a duplicate number on the same team.",
    )


class MatchPlayerCreate(MatchJoinIn):
    """Operator checking a player in at the pitch, for someone without a phone."""

    phone: str = Field(min_length=6, max_length=24)
    name: str | None = Field(default=None, max_length=120)
    allow_duplicate_jersey: bool = False


__all__ = [
    "FieldRef",
    "MatchCreate",
    "MatchDetail",
    "MatchJoinIn",
    "MatchJoinPreview",
    "MatchPlayerCreate",
    "MatchPlayerOut",
    "MatchPlayerUpdate",
    "MatchSummary",
    "MatchUpdate",
    "ORMModel",
    "VenueRef",
    "VideoRef",
]
