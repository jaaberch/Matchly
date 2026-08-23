"""Recording lifecycle: start, stop, upload, process.

Uploads are authenticated by *either* venue staff or the field's capture agent —
the agent is a machine with a per-camera token, and it is the thing that actually
pushes bytes. Everything else here is staff-only.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, status
from sqlalchemy import select

from matchly_shared.domain import Camera, Match, User
from matchly_shared.logging import get_logger

from ...core.errors import PermissionDenied
from ...schemas.video import (
    JobOut,
    ProcessOut,
    SegmentCompleteIn,
    SegmentOut,
    UploadCompleteIn,
    UploadTargetIn,
    UploadTargetOut,
    VideoOut,
)
from ...services import job_queue, match_service, venue_service, video_service
from ..deps import OptionalUser, SessionDep, SettingsDep, StorageDep

logger = get_logger(__name__)
router = APIRouter(prefix="/matches", tags=["video"])


def _authorise_uploader(
    session, *, match: Match, user: User | None, camera_token: str | None
) -> str:
    """Venue staff or the field's capture agent. Returns which one, for the log."""
    if camera_token:
        camera = session.scalars(select(Camera).where(Camera.field_id == match.field_id)).first()
        if camera is None:
            raise PermissionDenied("This field has no camera.")
        venue_service.authenticate_camera(session, camera_id=camera.id, token=camera_token)
        return "agent"

    if user is None:
        raise PermissionDenied("Venue staff or a camera token is required.")
    match_service.require_operator_access(session, user=user, match=match)
    return "operator"


def _staff_only(session, *, match_id: uuid.UUID, user: User | None) -> Match:
    if user is None:
        raise PermissionDenied("Venue staff access is required.")
    match = match_service.get_match(session, match_id)
    match_service.require_operator_access(session, user=user, match=match)
    return match


# ── Lifecycle ────────────────────────────────────────────────────────────
@router.post(
    "/{match_id}/start",
    summary="Start recording",
    description="Idempotent: starting a match that is already recording returns its state.",
    responses={409: {"description": "MATCH_NOT_STARTABLE or NO_CAMERA"}},
)
def start_match(
    match_id: uuid.UUID, session: SessionDep, settings: SettingsDep, user: OptionalUser
) -> dict:
    match = _staff_only(session, match_id=match_id, user=user)
    video_service.start_match(session, match=match, settings=settings)
    camera = session.scalars(select(Camera).where(Camera.field_id == match.field_id)).first()
    return {
        "match_id": match.id,
        "status": match.status.value,
        "started_at": match.started_at,
        "camera": {
            "id": camera.id,
            "online": venue_service.camera_is_online(camera, settings=settings),
        }
        if camera
        else None,
    }


@router.post(
    "/{match_id}/stop",
    summary="Stop recording",
    description="Idempotent. Moves the match to UPLOADING, which is resumable, not final.",
)
def stop_match(match_id: uuid.UUID, session: SessionDep, user: OptionalUser) -> dict:
    match = _staff_only(session, match_id=match_id, user=user)
    video_service.stop_match(session, match=match)
    return {
        "match_id": match.id,
        "status": match.status.value,
        "stopped_at": match.stopped_at,
    }


# ── Upload ───────────────────────────────────────────────────────────────
@router.post(
    "/{match_id}/video",
    response_model=UploadTargetOut,
    summary="Request a presigned upload target",
    description=(
        "Authenticated by venue staff or by the field's capture agent via "
        "`X-Camera-Token`. Bytes go straight to object storage — never through "
        "this API."
    ),
)
def request_upload(
    match_id: uuid.UUID,
    payload: UploadTargetIn,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: OptionalUser,
    x_camera_token: Annotated[str | None, Header()] = None,
) -> UploadTargetOut:
    match = match_service.get_match(session, match_id)
    actor = _authorise_uploader(session, match=match, user=user, camera_token=x_camera_token)
    target = video_service.request_upload_target(
        session,
        match=match,
        kind=payload.kind,
        segment_index=payload.segment_index,
        content_type=payload.content_type,
        storage=storage,
        settings=settings,
    )
    logger.info(
        "video.upload_target_issued",
        extra={"match_id": str(match_id), "actor": actor, "kind": payload.kind},
    )
    return UploadTargetOut(**target)


@router.post(
    "/{match_id}/video/segments",
    response_model=SegmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Confirm a segment has been uploaded",
    description=(
        "The object is verified in storage before the row is written, so a "
        "segment can never be marked complete without actually arriving."
    ),
)
def complete_segment(
    match_id: uuid.UUID,
    payload: SegmentCompleteIn,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: OptionalUser,
    x_camera_token: Annotated[str | None, Header()] = None,
) -> SegmentOut:
    match = match_service.get_match(session, match_id)
    _authorise_uploader(session, match=match, user=user, camera_token=x_camera_token)
    segment = video_service.complete_segment(
        session,
        match=match,
        segment_index=payload.segment_index,
        size_bytes=payload.size_bytes,
        duration=payload.duration,
        storage=storage,
        settings=settings,
    )
    return SegmentOut.model_validate(segment)


@router.post(
    "/{match_id}/video/complete",
    response_model=VideoOut,
    summary="Mark the recording complete",
    responses={
        409: {"description": "SEGMENTS_INCOMPLETE, RECORDING_MISSING or RECORDING_TOO_SMALL"}
    },
)
def complete_upload(
    match_id: uuid.UUID,
    payload: UploadCompleteIn,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: OptionalUser,
    x_camera_token: Annotated[str | None, Header()] = None,
) -> VideoOut:
    match = match_service.get_match(session, match_id)
    _authorise_uploader(session, match=match, user=user, camera_token=x_camera_token)
    video = video_service.complete_upload(
        session,
        match=match,
        expected_segments=payload.expected_segments,
        storage=storage,
        settings=settings,
    )
    return _video_out(video, storage=storage, settings=settings)


# ── Processing ───────────────────────────────────────────────────────────
@router.post(
    "/{match_id}/process",
    response_model=ProcessOut,
    summary="Run the processing pipeline",
    description=(
        "Enqueues the pipeline and returns immediately — no video work happens in "
        "a request handler. `force=true` re-runs steps that already succeeded."
    ),
)
def process_match(
    match_id: uuid.UUID,
    session: SessionDep,
    user: OptionalUser,
    force: Annotated[bool, Query(description="Re-run completed steps")] = False,
) -> ProcessOut:
    match = _staff_only(session, match_id=match_id, user=user)
    video = video_service.mark_processing(session, match=match)
    session.commit()

    task_id = job_queue.enqueue_processing(video.id, force=force)
    logger.info(
        "video.processing_enqueued",
        extra={"video_id": str(video.id), "task_id": task_id, "force": force},
    )
    return ProcessOut(
        video_id=video.id,
        status=video.status,
        task_id=task_id,
        forced=force,
        detail="Processing has been queued.",
    )


# ── Status ───────────────────────────────────────────────────────────────
@router.get(
    "/{match_id}/video",
    response_model=VideoOut,
    summary="Recording and per-step processing state",
)
def get_video(
    match_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: OptionalUser,
) -> VideoOut:
    if user is None:
        raise PermissionDenied("Authentication is required.")
    match = match_service.get_match(session, match_id)
    if not match_service.can_view(session, user=user, match=match):
        raise PermissionDenied("You do not have access to this match.")
    return _video_out(
        video_service.get_video(session, match=match), storage=storage, settings=settings
    )


def _video_out(video, *, storage, settings) -> VideoOut:
    return VideoOut(
        id=video.id,
        match_id=video.match_id,
        status=video.status,
        duration=video.duration,
        size_bytes=video.size_bytes,
        width=video.width,
        height=video.height,
        fps=video.fps,
        has_audio=video.has_audio,
        failure_reason=video.failure_reason,
        purge_after=video.purge_after,
        created_at=video.created_at,
        segments=[SegmentOut.model_validate(segment) for segment in video.segments],
        jobs=[JobOut.model_validate(job) for job in sorted(video.jobs, key=lambda j: j.step.value)],
        playback_url=video_service.signed_playback_url(video, storage=storage, settings=settings),
    )
