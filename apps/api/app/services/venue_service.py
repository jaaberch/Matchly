"""Venues, fields and cameras.

The venue graph is small and slow-changing: a venue has fields, a field has one
camera. What matters here is authorisation — every route is scoped by
``venue_members``, not merely by the operator role bit — and that camera
credentials are handled like passwords.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from matchly_shared.config import Settings
from matchly_shared.domain import (
    Camera,
    CameraStatus,
    Field,
    Match,
    MatchStatus,
    User,
    UserRole,
    Venue,
    VenueMember,
    VenueRole,
)
from matchly_shared.logging import get_logger
from matchly_shared.timeutil import utcnow

from ..core.errors import Conflict, NotFound, PermissionDenied
from ..core.phone import normalize_phone

logger = get_logger(__name__)


# ── Venues ───────────────────────────────────────────────────────────────
def create_venue(session: Session, *, data, settings: Settings) -> Venue:
    venue = Venue(
        name=data.name.strip(),
        location=data.location.strip(),
        timezone=data.timezone,
        video_retention_days=(data.video_retention_days or settings.default_video_retention_days),
        recording_disclosure=data.recording_disclosure,
    )
    session.add(venue)
    session.flush()
    logger.info("venue.created", extra={"venue_id": str(venue.id)})
    return venue


def visible_venues_statement(user: User):
    """Admins see every venue; operators see only the ones they are a member of."""
    statement = select(Venue).order_by(Venue.name)
    if user.role is UserRole.ADMIN:
        return statement
    return statement.join(VenueMember, VenueMember.venue_id == Venue.id).where(
        VenueMember.user_id == user.id
    )


def get_venue(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.get(Venue, venue_id)
    if venue is None:
        raise NotFound("Venue not found.")
    return venue


def get_venue_with_fields(session: Session, venue_id: uuid.UUID) -> Venue:
    venue = session.scalars(
        select(Venue)
        .where(Venue.id == venue_id)
        .options(selectinload(Venue.fields).selectinload(Field.camera))
    ).first()
    if venue is None:
        raise NotFound("Venue not found.")
    return venue


def update_venue(session: Session, *, venue: Venue, data) -> Venue:
    for attribute in (
        "name",
        "location",
        "timezone",
        "video_retention_days",
        "recording_disclosure",
    ):
        value = getattr(data, attribute)
        if value is not None:
            setattr(venue, attribute, value)
    session.flush()
    return venue


# ── Membership ───────────────────────────────────────────────────────────
def add_member(session: Session, *, venue: Venue, data) -> tuple[VenueMember, User]:
    """Grant a phone number operator access to a venue.

    Venue staff are onboarded by phone number, the same identity everyone else
    uses, so an operator account is created here if one does not exist yet. They
    sign in with the normal OTP flow.
    """
    phone = normalize_phone(data.phone)
    user = session.scalars(
        select(User).where(User.phone == phone, User.deleted_at.is_(None))
    ).first()

    if user is None:
        user = User(
            name=(data.name or "").strip() or f"Operator {phone[-4:]}",
            phone=phone,
            role=UserRole.VENUE_OPERATOR,
        )
        session.add(user)
        session.flush()
    elif user.role is UserRole.PLAYER:
        # Never downgrade an admin; a player becomes an operator.
        user.role = UserRole.VENUE_OPERATOR

    existing = session.scalars(
        select(VenueMember).where(VenueMember.venue_id == venue.id, VenueMember.user_id == user.id)
    ).first()
    if existing is not None:
        existing.role = data.role
        session.flush()
        return existing, user

    member = VenueMember(venue_id=venue.id, user_id=user.id, role=data.role)
    session.add(member)
    session.flush()
    logger.info(
        "venue.member_added",
        extra={"venue_id": str(venue.id), "user_id": str(user.id), "role": data.role.value},
    )
    return member, user


def list_members(session: Session, venue_id: uuid.UUID) -> list[tuple[VenueMember, User]]:
    rows = session.execute(
        select(VenueMember, User)
        .join(User, User.id == VenueMember.user_id)
        .where(VenueMember.venue_id == venue_id)
        .order_by(User.name)
    ).all()
    return [(member, user) for member, user in rows]


def require_venue_manager(session: Session, *, user: User, venue_id: uuid.UUID) -> None:
    """Managing staff and venue settings needs MANAGER, not merely OPERATOR."""
    if user.role is UserRole.ADMIN:
        return
    membership = session.scalars(
        select(VenueMember).where(VenueMember.venue_id == venue_id, VenueMember.user_id == user.id)
    ).first()
    if membership is None or membership.role is not VenueRole.MANAGER:
        raise PermissionDenied("Venue manager access is required.")


# ── Fields ───────────────────────────────────────────────────────────────
def create_field(session: Session, *, venue: Venue, data) -> Field:
    name = data.name.strip()
    duplicate = session.scalars(
        select(Field).where(Field.venue_id == venue.id, Field.name == name)
    ).first()
    if duplicate is not None:
        raise Conflict(
            f"This venue already has a field called {name!r}.",
            code="FIELD_NAME_TAKEN",
            details={"name": name},
        )

    field = Field(venue_id=venue.id, name=name)
    session.add(field)
    session.flush()
    logger.info("field.created", extra={"field_id": str(field.id), "venue_id": str(venue.id)})
    return field


def list_fields(session: Session, venue_id: uuid.UUID) -> list[Field]:
    return list(
        session.scalars(
            select(Field)
            .where(Field.venue_id == venue_id)
            .options(selectinload(Field.camera))
            .order_by(Field.name)
        ).all()
    )


def get_field(session: Session, field_id: uuid.UUID) -> Field:
    field = session.scalars(
        select(Field).where(Field.id == field_id).options(selectinload(Field.camera))
    ).first()
    if field is None:
        raise NotFound("Field not found.")
    return field


# ── Cameras ──────────────────────────────────────────────────────────────
def hash_camera_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def attach_camera(session: Session, *, field: Field, data) -> tuple[Camera, str]:
    """Attach or replace the camera on a field, returning its one-time token.

    One camera per field in the MVP, so re-attaching replaces the existing row
    and issues a fresh credential — which is also how a stolen token is rotated.
    """
    raw_token = secrets.token_urlsafe(32)

    camera = field.camera
    if camera is None:
        camera = Camera(field_id=field.id, name=data.name.strip())
        session.add(camera)
    else:
        camera.name = data.name.strip()

    camera.stream_url = data.stream_url
    camera.token_hash = hash_camera_token(raw_token)
    camera.status = CameraStatus.OFFLINE
    camera.last_seen = None
    session.flush()

    logger.info("camera.attached", extra={"camera_id": str(camera.id), "field_id": str(field.id)})
    return camera, raw_token


def get_camera(session: Session, camera_id: uuid.UUID) -> Camera:
    camera = session.get(Camera, camera_id)
    if camera is None:
        raise NotFound("Camera not found.")
    return camera


def authenticate_camera(session: Session, *, camera_id: uuid.UUID, token: str) -> Camera:
    camera = session.get(Camera, camera_id)
    if camera is None or not camera.token_hash:
        raise PermissionDenied("Unknown camera or no token issued.")
    if not secrets.compare_digest(camera.token_hash, hash_camera_token(token)):
        raise PermissionDenied("Invalid camera token.")
    return camera


def record_heartbeat(session: Session, *, camera: Camera, status: CameraStatus) -> Camera:
    camera.status = status
    camera.last_seen = utcnow()
    session.flush()
    return camera


def current_match_id(session: Session, *, field_id: uuid.UUID) -> uuid.UUID | None:
    """The match this camera is currently recording, if any."""
    match = session.scalars(
        select(Match)
        .where(Match.field_id == field_id, Match.status == MatchStatus.RECORDING)
        .order_by(Match.starts_at.desc())
        .limit(1)
    ).first()
    return match.id if match else None


def camera_is_online(camera: Camera, *, settings: Settings) -> bool:
    return camera.is_online(offline_after_seconds=settings.camera_offline_after_seconds)
