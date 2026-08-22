"""Venue, field and camera management.

Every route here is scoped by venue membership, not merely by the operator role
bit: being a `VENUE_OPERATOR` says you operate *a* venue, never *this* one.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from matchly_shared.domain import UserRole

from ...core.errors import PermissionDenied
from ...core.pagination import Page, PageParamsDep, build_page, paginate
from ...schemas.venue import (
    CameraCreate,
    CameraCreated,
    FieldCreate,
    FieldOut,
    VenueCreate,
    VenueDetail,
    VenueMemberCreate,
    VenueMemberOut,
    VenueOut,
    VenueUpdate,
)
from ...services import venue_service
from ..deps import AdminUser, CurrentUser, SessionDep, SettingsDep
from .presenters import field_out, venue_detail

router = APIRouter(prefix="/venues", tags=["venues"])


def _assert_access(session, user, venue_id: uuid.UUID) -> None:
    from ...services.match_service import has_venue_access

    if not has_venue_access(session, user=user, venue_id=venue_id):
        raise PermissionDenied("You do not have access to this venue.")


# ── Venues ───────────────────────────────────────────────────────────────
@router.get("", response_model=Page[VenueOut], summary="List venues you can access")
def list_venues(
    session: SessionDep,
    user: CurrentUser,
    params: PageParamsDep,
) -> dict:
    if user.role is UserRole.PLAYER:
        raise PermissionDenied("Venue access is required.")
    rows, total = paginate(session, venue_service.visible_venues_statement(user), params)
    return build_page([VenueOut.model_validate(row) for row in rows], total, params)


@router.post(
    "",
    response_model=VenueOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a venue (platform admin)",
)
def create_venue(
    payload: VenueCreate, session: SessionDep, settings: SettingsDep, _: AdminUser
) -> VenueOut:
    venue = venue_service.create_venue(session, data=payload, settings=settings)
    return VenueOut.model_validate(venue)


@router.get("/{venue_id}", response_model=VenueDetail, summary="Venue with fields and cameras")
def get_venue(
    venue_id: uuid.UUID, session: SessionDep, settings: SettingsDep, user: CurrentUser
) -> VenueDetail:
    _assert_access(session, user, venue_id)
    venue = venue_service.get_venue_with_fields(session, venue_id)
    return venue_detail(venue, settings=settings)


@router.patch("/{venue_id}", response_model=VenueOut, summary="Update venue settings")
def update_venue(
    venue_id: uuid.UUID, payload: VenueUpdate, session: SessionDep, user: CurrentUser
) -> VenueOut:
    venue_service.require_venue_manager(session, user=user, venue_id=venue_id)
    venue = venue_service.get_venue(session, venue_id)
    return VenueOut.model_validate(venue_service.update_venue(session, venue=venue, data=payload))


# ── Staff ────────────────────────────────────────────────────────────────
@router.get("/{venue_id}/members", response_model=list[VenueMemberOut], summary="Venue staff")
def list_members(
    venue_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[VenueMemberOut]:
    _assert_access(session, user, venue_id)
    return [
        VenueMemberOut(
            id=member.id,
            venue_id=member.venue_id,
            user_id=member.user_id,
            name=member_user.name,
            role=member.role,
            created_at=member.created_at,
        )
        for member, member_user in venue_service.list_members(session, venue_id)
    ]


@router.post(
    "/{venue_id}/members",
    response_model=VenueMemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Grant a phone number operator access",
)
def add_member(
    venue_id: uuid.UUID, payload: VenueMemberCreate, session: SessionDep, user: CurrentUser
) -> VenueMemberOut:
    venue_service.require_venue_manager(session, user=user, venue_id=venue_id)
    venue = venue_service.get_venue(session, venue_id)
    member, member_user = venue_service.add_member(session, venue=venue, data=payload)
    return VenueMemberOut(
        id=member.id,
        venue_id=member.venue_id,
        user_id=member.user_id,
        name=member_user.name,
        role=member.role,
        created_at=member.created_at,
    )


# ── Fields ───────────────────────────────────────────────────────────────
@router.get("/{venue_id}/fields", response_model=list[FieldOut], summary="Fields at a venue")
def list_fields(
    venue_id: uuid.UUID, session: SessionDep, settings: SettingsDep, user: CurrentUser
) -> list[FieldOut]:
    _assert_access(session, user, venue_id)
    return [
        field_out(field, settings=settings)
        for field in venue_service.list_fields(session, venue_id)
    ]


@router.post(
    "/{venue_id}/fields",
    response_model=FieldOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a field",
)
def create_field(
    venue_id: uuid.UUID,
    payload: FieldCreate,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUser,
) -> FieldOut:
    _assert_access(session, user, venue_id)
    venue = venue_service.get_venue(session, venue_id)
    field = venue_service.create_field(session, venue=venue, data=payload)
    return field_out(field, settings=settings)


# ── Camera attachment (field-scoped, so it lives on its own router) ──────
fields_router = APIRouter(prefix="/fields", tags=["venues"])


@fields_router.get("/{field_id}", response_model=FieldOut, summary="Field detail")
def get_field(
    field_id: uuid.UUID, session: SessionDep, settings: SettingsDep, user: CurrentUser
) -> FieldOut:
    field = venue_service.get_field(session, field_id)
    _assert_access(session, user, field.venue_id)
    return field_out(field, settings=settings)


@fields_router.post(
    "/{field_id}/camera",
    response_model=CameraCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Attach or replace the camera on a field",
    description=(
        "Returns the capture agent's token exactly once. It is stored hashed and "
        "cannot be recovered — re-attach the camera to issue a new one."
    ),
)
def attach_camera(
    field_id: uuid.UUID,
    payload: CameraCreate,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUser,
) -> CameraCreated:
    field = venue_service.get_field(session, field_id)
    _assert_access(session, user, field.venue_id)
    camera, token = venue_service.attach_camera(session, field=field, data=payload)
    from .presenters import camera_out

    return CameraCreated(camera=camera_out(camera, settings=settings), token=token)


@fields_router.delete(
    "/{field_id}/camera",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach the camera from a field",
)
def detach_camera(field_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    field = venue_service.get_field(session, field_id)
    _assert_access(session, user, field.venue_id)
    if field.camera is not None:
        session.delete(field.camera)
        session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
