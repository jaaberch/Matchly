"""Camera status and heartbeat.

The heartbeat is the only endpoint in the platform authenticated by something
other than a user token: the on-site capture agent is a machine, not a person, so
it presents a per-camera shared secret in ``X-Camera-Token``.

Online/offline is derived from ``last_seen``, never read from ``status`` alone —
an agent that dies without saying goodbye would otherwise show as ONLINE forever,
and a venue would find out it had no recording only after the match.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header

from ...core.errors import PermissionDenied
from ...schemas.venue import CameraHeartbeatIn, CameraStatusOut
from ...services import venue_service
from ..deps import CurrentUser, SessionDep, SettingsDep

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _status_out(camera, *, session, settings) -> CameraStatusOut:
    return CameraStatusOut(
        id=camera.id,
        field_id=camera.field_id,
        name=camera.name,
        status=camera.status,
        last_seen=camera.last_seen,
        online=venue_service.camera_is_online(camera, settings=settings),
        current_match_id=venue_service.current_match_id(session, field_id=camera.field_id),
    )


@router.get("/{camera_id}/status", response_model=CameraStatusOut, summary="Camera status")
def camera_status(
    camera_id: uuid.UUID, session: SessionDep, settings: SettingsDep, user: CurrentUser
) -> CameraStatusOut:
    camera = venue_service.get_camera(session, camera_id)
    field = venue_service.get_field(session, camera.field_id)
    from ...services.match_service import has_venue_access

    if not has_venue_access(session, user=user, venue_id=field.venue_id):
        raise PermissionDenied("You do not have access to this venue.")
    return _status_out(camera, session=session, settings=settings)


@router.post(
    "/{camera_id}/heartbeat",
    response_model=CameraStatusOut,
    summary="Capture agent heartbeat",
    description="Authenticated with the camera token issued when the camera was attached.",
    responses={403: {"description": "Missing or invalid camera token"}},
)
def heartbeat(
    camera_id: uuid.UUID,
    payload: CameraHeartbeatIn,
    session: SessionDep,
    settings: SettingsDep,
    x_camera_token: Annotated[str | None, Header()] = None,
) -> CameraStatusOut:
    if not x_camera_token:
        raise PermissionDenied("A camera token is required.")
    camera = venue_service.authenticate_camera(session, camera_id=camera_id, token=x_camera_token)
    venue_service.record_heartbeat(session, camera=camera, status=payload.status)
    return _status_out(camera, session=session, settings=settings)
