"""SQLAlchemy models — the single source of truth for the Matchly schema.

Owned here (rather than inside the API) because the background workers persist
their own results and must not duplicate the schema. Migrations live in
``apps/api/alembic`` and are the only thing allowed to change the database.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

from ..timeutil import ensure_utc, utcnow
from .columns import GUID, JSONBType, new_uuid
from .enums import (
    CameraStatus,
    HighlightType,
    JobStatus,
    JobStep,
    MatchStatus,
    Team,
    UserRole,
    VenueRole,
    VideoStatus,
)


def _enum(python_enum: type, name: str) -> SAEnum:
    """Native PostgreSQL enum storing member *values*."""
    return SAEnum(
        python_enum,
        name=name,
        native_enum=True,
        values_callable=lambda e: [member.value for member in e],
        validate_strings=True,
    )


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), primary_key=True, default=new_uuid)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────────────────────
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: E.164, e.g. +212612345678. Unique among non-deleted users.
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    avatar: Mapped[str | None] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(
        _enum(UserRole, "user_role"), nullable=False, default=UserRole.PLAYER
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    match_players: Mapped[list[MatchPlayer]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    venue_memberships: Mapped[list[VenueMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "users_phone_key",
            "phone",
            unique=True,
            postgresql_where=deleted_at.is_(None),
            sqlite_where=deleted_at.is_(None),
        ),
    )

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None


class OtpChallenge(Base):
    """A pending phone verification. The code itself is never stored."""

    __tablename__ = "otp_challenges"

    id: Mapped[uuid.UUID] = _pk()
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("otp_challenges_phone_idx", "phone", "created_at"),)


class RefreshToken(Base):
    """Rotating refresh token. Only the hash is stored, like a password."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


# ─────────────────────────────────────────────────────────────────────────────
# Venue graph
# ─────────────────────────────────────────────────────────────────────────────
class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Casablanca")
    #: Retention for original recordings; derived clips are kept longer.
    video_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    recording_disclosure: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    fields: Mapped[list[Field]] = relationship(back_populates="venue", cascade="all, delete-orphan")
    members: Mapped[list[VenueMember]] = relationship(
        back_populates="venue", cascade="all, delete-orphan"
    )


class VenueMember(Base):
    """Venue-level access control: who may operate which venue."""

    __tablename__ = "venue_members"

    id: Mapped[uuid.UUID] = _pk()
    venue_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("venues.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[VenueRole] = mapped_column(
        _enum(VenueRole, "venue_role"), nullable=False, default=VenueRole.OPERATOR
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    venue: Mapped[Venue] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="venue_memberships")

    __table_args__ = (UniqueConstraint("venue_id", "user_id", name="venue_members_unique"),)


class Field(Base):
    __tablename__ = "fields"

    id: Mapped[uuid.UUID] = _pk()
    venue_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("venues.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    venue: Mapped[Venue] = relationship(back_populates="fields")
    #: The stored edge is ``cameras.field_id`` (see ARCHITECTURE.md §4.2); this
    #: relationship is what exposes ``field.camera`` / ``camera_id`` on reads.
    camera: Mapped[Camera | None] = relationship(
        back_populates="field", cascade="all, delete-orphan", uselist=False
    )
    matches: Mapped[list[Match]] = relationship(back_populates="field")

    __table_args__ = (UniqueConstraint("venue_id", "name", name="fields_venue_name_unique"),)

    @property
    def camera_id(self) -> uuid.UUID | None:
        return self.camera.id if self.camera else None


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = _pk()
    #: Unique: one camera per field in the MVP.
    field_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[CameraStatus] = mapped_column(
        _enum(CameraStatus, "camera_status"), nullable=False, default=CameraStatus.OFFLINE
    )
    #: RTSP URL, read by the on-site capture agent only. Never returned to players.
    stream_url: Mapped[str | None] = mapped_column(Text)
    #: Shared secret the on-site capture agent presents on every heartbeat and
    #: upload. Stored hashed, like a password; the plaintext is shown once, at
    #: the moment the camera is attached to a field.
    token_hash: Mapped[str | None] = mapped_column(String(255))
    last_seen: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    field: Mapped[Field] = relationship(back_populates="camera")

    def is_online(self, *, offline_after_seconds: int) -> bool:
        """Online is derived from the heartbeat, never trusted from ``status`` alone.

        ``last_seen`` is coerced to UTC because SQLite returns naive datetimes
        while PostgreSQL returns aware ones, and subtracting the two raises.
        """
        last_seen = ensure_utc(self.last_seen)
        if last_seen is None:
            return False
        return (utcnow() - last_seen).total_seconds() <= offline_after_seconds


# ─────────────────────────────────────────────────────────────────────────────
# Match
# ─────────────────────────────────────────────────────────────────────────────
class Match(Base, TimestampMixin):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = _pk()
    field_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("fields.id", ondelete="RESTRICT"), nullable=False
    )
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[MatchStatus] = mapped_column(
        _enum(MatchStatus, "match_status"), nullable=False, default=MatchStatus.SCHEDULED
    )
    #: QR target: /match/join/{join_code}
    join_code: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(String(160))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)

    field: Mapped[Field] = relationship(back_populates="matches")
    players: Mapped[list[MatchPlayer]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    video: Mapped[Video | None] = relationship(
        back_populates="match", cascade="all, delete-orphan", uselist=False
    )
    highlights: Mapped[list[Highlight]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="matches_time_order"),
        Index("matches_field_starts_idx", "field_id", "starts_at"),
        Index("matches_status_idx", "status", "starts_at"),
    )

    @property
    def video_url(self) -> str | None:
        """Derived, read-only: the processed replay if we have one, else the master.

        ``videos`` is the source of truth; this exists so ``match.video_url`` reads
        exactly as specified without a second column to keep in sync.
        """
        if self.video is None:
            return None
        return self.video.processed_url or self.video.original_url


class MatchPlayer(Base):
    __tablename__ = "match_players"

    id: Mapped[uuid.UUID] = _pk()
    match_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    team: Mapped[Team] = mapped_column(_enum(Team, "team"), nullable=False)
    jersey_number: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Set when an administrator allows a duplicate number on the same team.
    jersey_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Participation consent; check-in cannot complete without it.
    consent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    match: Mapped[Match] = relationship(back_populates="players")
    user: Mapped[User] = relationship(back_populates="match_players")
    highlights: Mapped[list[Highlight]] = relationship(back_populates="player")
    tracks: Mapped[list[PlayerTrack]] = relationship(back_populates="player")

    __table_args__ = (
        CheckConstraint(
            "jersey_number >= 0 AND jersey_number <= 99", name="match_players_jersey_range"
        ),
        UniqueConstraint("match_id", "user_id", name="match_players_user_unique"),
        # Duplicate numbers are blocked per team unless explicitly overridden.
        Index(
            "match_players_jersey_key",
            "match_id",
            "team",
            "jersey_number",
            unique=True,
            postgresql_where=jersey_override.is_(False),
            sqlite_where=jersey_override.is_(False),
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Video & processing
# ─────────────────────────────────────────────────────────────────────────────
class Video(Base, TimestampMixin):
    """One recording per match.

    ``*_url`` columns hold storage URIs (``s3://bucket/key``), not public links.
    The API signs them at read time so match video is never publicly addressable.
    """

    __tablename__ = "videos"

    id: Mapped[uuid.UUID] = _pk()
    match_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    original_url: Mapped[str | None] = mapped_column(Text)
    processed_url: Mapped[str | None] = mapped_column(Text)
    #: Low-resolution copy the CV steps read. Never shown to users.
    proxy_url: Mapped[str | None] = mapped_column(Text)
    duration: Mapped[float | None] = mapped_column(Float)
    status: Mapped[VideoStatus] = mapped_column(
        _enum(VideoStatus, "video_status"), nullable=False, default=VideoStatus.PENDING
    )
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    has_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Raw ffprobe output, kept for debugging bad recordings.
    video_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONBType, nullable=False, default=dict
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)
    #: Retention deadline for the original; set from the venue's policy.
    purge_after: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    match: Mapped[Match] = relationship(back_populates="video")
    jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )
    #: Ordered by position in the recording, never by arrival time.
    segments: Mapped[list[VideoSegment]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        order_by="VideoSegment.segment_index",
    )
    tracks: Mapped[list[PlayerTrack]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )
    highlights: Mapped[list[Highlight]] = relationship(back_populates="video")


class VideoSegment(Base):
    """One chunk of a recording as uploaded by the on-site capture agent.

    Recording is segmented rather than streamed as one 60-minute file: local disk
    is the durability buffer, each segment uploads independently and resumably,
    and the video is only complete when every expected segment has arrived. A
    whole-match network outage therefore leaves the match in UPLOADING, not lost.
    """

    __tablename__ = "video_segments"

    id: Mapped[uuid.UUID] = _pk()
    video_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    #: 0-based position in the recording; ordering is by this, never by arrival.
    #: Named ``segment_index`` because ``index`` is a reserved word in SQL.
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_url: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration: Mapped[float | None] = mapped_column(Float)
    uploaded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    video: Mapped[Video] = relationship(back_populates="segments")

    __table_args__ = (
        UniqueConstraint("video_id", "segment_index", name="video_segments_index_unique"),
        CheckConstraint("segment_index >= 0", name="video_segments_index_positive"),
    )


class ProcessingJob(Base, TimestampMixin):
    """One row per (video, step). The unique constraint is what makes retries idempotent."""

    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = _pk()
    video_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[JobStep] = mapped_column(_enum(JobStep, "job_step"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), nullable=False, default=JobStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    #: Hash of the step's inputs; a changed fingerprint re-runs a succeeded step.
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    video: Mapped[Video] = relationship(back_populates="jobs")

    __table_args__ = (
        UniqueConstraint("video_id", "step", name="processing_jobs_step_unique"),
        Index("processing_jobs_status_idx", "status", "updated_at"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# AI output
# ─────────────────────────────────────────────────────────────────────────────
class PlayerTrack(Base):
    """A tracked player across frames, with the temporally-voted jersey number."""

    __tablename__ = "player_tracks"

    id: Mapped[uuid.UUID] = _pk()
    video_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    track_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    jersey_number: Mapped[int | None] = mapped_column(Integer)
    jersey_confidence: Mapped[float | None] = mapped_column(Float)
    player_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("match_players.id", ondelete="SET NULL")
    )
    first_seen: Mapped[float] = mapped_column(Float, nullable=False)
    last_seen: Mapped[float] = mapped_column(Float, nullable=False)
    #: Per-frame votes, retained so a bad attribution can be audited.
    samples: Mapped[list[Any]] = mapped_column(JSONBType, nullable=False, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    video: Mapped[Video] = relationship(back_populates="tracks")
    player: Mapped[MatchPlayer | None] = relationship(back_populates="tracks")

    __table_args__ = (UniqueConstraint("video_id", "track_ref", name="player_tracks_ref_unique"),)


class Highlight(Base):
    __tablename__ = "highlights"

    id: Mapped[uuid.UUID] = _pk()
    match_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="CASCADE")
    )
    #: Optional: null when jersey recognition could not attribute the moment.
    player_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("match_players.id", ondelete="SET NULL")
    )
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[HighlightType] = mapped_column(
        _enum(HighlightType, "highlight_type"), nullable=False, default=HighlightType.GENERIC
    )
    video_url: Mapped[str | None] = mapped_column(Text)
    #: 9:16 export for social sharing; generated lazily.
    video_url_vertical: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    #: e.g. {"motion": 0.94, "player_density": 0.88, "audio_peak": 0.76}
    signals: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    match: Mapped[Match] = relationship(back_populates="highlights")
    video: Mapped[Video | None] = relationship(back_populates="highlights")
    player: Mapped[MatchPlayer | None] = relationship(back_populates="highlights")

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="highlights_time_order"),
        Index("highlights_match_score_idx", "match_id", "score"),
        Index("highlights_player_idx", "player_id", "created_at"),
    )

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


__all__ = [
    "Base",
    "User",
    "OtpChallenge",
    "RefreshToken",
    "Venue",
    "VenueMember",
    "Field",
    "Camera",
    "Match",
    "MatchPlayer",
    "Video",
    "ProcessingJob",
    "PlayerTrack",
    "Highlight",
]
