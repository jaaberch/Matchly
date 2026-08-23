"""Match recording lifecycle and video upload.

The rule this file exists to enforce: **a match recording must never be lost.**

A 60-minute 4K master is 8–30 GB, so it never passes through the API. The capture
agent gets a presigned URL and writes straight to object storage. Recording is
segmented rather than streamed as one file, because local disk on the pitch is
the durability buffer: each segment uploads independently and resumably, and the
video is complete only when every expected segment has arrived. A whole-match
network outage leaves the match in UPLOADING — a resumable state, not a failure.

Start and stop are idempotent. Venue staff press these buttons on a phone at the
side of a pitch, and a double tap must never be an error.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from matchly_shared.config import Settings
from matchly_shared.domain import (
    Camera,
    Match,
    MatchStatus,
    Video,
    VideoSegment,
    VideoStatus,
)
from matchly_shared.logging import get_logger
from matchly_shared.storage import ObjectNotFound, ObjectStorage, keys, parse_uri
from matchly_shared.timeutil import utcnow

from ..core.errors import Conflict, NotFound

logger = get_logger(__name__)

#: Below this a "recording" is a truncated file, not a match.
MIN_PLAUSIBLE_BYTES = 1024

#: Statuses from which a recording may still be uploaded.
UPLOADABLE = (MatchStatus.RECORDING, MatchStatus.UPLOADING)


# ── Video row ────────────────────────────────────────────────────────────
def get_or_create_video(session: Session, *, match: Match) -> Video:
    """One video per match. Created on first need, never duplicated."""
    if match.video is not None:
        return match.video

    video = Video(match_id=match.id, status=VideoStatus.PENDING)
    try:
        with session.begin_nested():
            session.add(video)
            session.flush()
    except IntegrityError:
        # Another request created it in the meantime.
        video = session.scalars(select(Video).where(Video.match_id == match.id)).one()
    session.refresh(match)
    return video


def get_video(session: Session, *, match: Match) -> Video:
    if match.video is None:
        raise NotFound("This match has no recording yet.")
    return match.video


# ── Lifecycle ────────────────────────────────────────────────────────────
def start_match(session: Session, *, match: Match, settings: Settings) -> Match:
    """SCHEDULED | CHECK_IN → RECORDING. Idempotent."""
    if match.status is MatchStatus.RECORDING:
        return match  # already rolling; a double tap is not an error
    if match.status not in (MatchStatus.SCHEDULED, MatchStatus.CHECK_IN):
        raise Conflict(
            "This match cannot be started from its current state.",
            code="MATCH_NOT_STARTABLE",
            details={"status": match.status.value},
        )

    camera = session.scalars(select(Camera).where(Camera.field_id == match.field_id)).first()
    if camera is None:
        # A field with no camera cannot record. That is a setup mistake, and
        # finding out after the match is far worse than finding out now.
        raise Conflict(
            "This field has no camera attached, so it cannot record.",
            code="NO_CAMERA",
            details={"field_id": str(match.field_id)},
        )

    match.status = MatchStatus.RECORDING
    match.started_at = utcnow()
    match.failure_reason = None
    get_or_create_video(session, match=match)
    session.flush()

    online = camera.is_online(offline_after_seconds=settings.camera_offline_after_seconds)
    if not online:
        # Not fatal: the heartbeat may simply be stale. The dashboard surfaces
        # this so staff can look at the camera before kick-off.
        logger.warning(
            "match.started_with_offline_camera",
            extra={"match_id": str(match.id), "camera_id": str(camera.id)},
        )
    logger.info("match.started", extra={"match_id": str(match.id), "camera_online": online})
    return match


def stop_match(session: Session, *, match: Match) -> Match:
    """RECORDING → UPLOADING. Idempotent."""
    if match.status in (MatchStatus.UPLOADING, MatchStatus.PROCESSING, MatchStatus.READY):
        return match
    if match.status is not MatchStatus.RECORDING:
        raise Conflict(
            "This match is not recording.",
            code="MATCH_NOT_RECORDING",
            details={"status": match.status.value},
        )

    match.status = MatchStatus.UPLOADING
    match.stopped_at = utcnow()
    video = get_or_create_video(session, match=match)
    if video.status is VideoStatus.PENDING:
        video.status = VideoStatus.UPLOADING
    session.flush()
    logger.info("match.stopped", extra={"match_id": str(match.id)})
    return match


# ── Upload ───────────────────────────────────────────────────────────────
def request_upload_target(
    session: Session,
    *,
    match: Match,
    kind: str,
    segment_index: int | None,
    content_type: str,
    storage: ObjectStorage,
    settings: Settings,
) -> dict:
    """Issue a presigned PUT so the recording never passes through the API."""
    if match.status not in UPLOADABLE:
        raise Conflict(
            "This match is not accepting a recording.",
            code="MATCH_NOT_UPLOADABLE",
            details={"status": match.status.value},
        )

    video = get_or_create_video(session, match=match)
    if video.status in (VideoStatus.PENDING, VideoStatus.UPLOADED):
        video.status = VideoStatus.UPLOADING

    bucket = settings.storage_bucket_originals
    if kind == "segment":
        if segment_index is None or segment_index < 0:
            raise Conflict("A segment needs a non-negative index.", code="INVALID_SEGMENT_INDEX")
        key = keys.segment_key(match.id, video.id, segment_index)
    else:
        key = keys.master_key(match.id, video.id)

    url = storage.signed_upload_url(
        bucket, key, ttl_seconds=settings.signed_url_ttl_seconds, content_type=content_type
    )
    session.flush()
    return {
        "video_id": video.id,
        "kind": kind,
        "segment_index": segment_index,
        "bucket": bucket,
        "storage_key": key,
        "upload_url": url,
        "method": "PUT",
        "expires_at": utcnow() + dt.timedelta(seconds=settings.signed_url_ttl_seconds),
    }


def complete_segment(
    session: Session,
    *,
    match: Match,
    segment_index: int,
    size_bytes: int | None,
    duration: float | None,
    storage: ObjectStorage,
    settings: Settings,
) -> VideoSegment:
    """Record that a segment has landed.

    The object is verified before the row is written, so the agent cannot mark a
    segment complete that never arrived — that is the whole point of tracking
    them.
    """
    video = get_or_create_video(session, match=match)
    bucket = settings.storage_bucket_originals
    key = keys.segment_key(match.id, video.id, segment_index)

    try:
        info = storage.stat(bucket, key)
    except ObjectNotFound as exc:
        raise Conflict(
            "That segment is not in storage. Upload it before marking it complete.",
            code="SEGMENT_MISSING",
            details={"segment_index": segment_index},
        ) from exc

    existing = session.scalars(
        select(VideoSegment).where(
            VideoSegment.video_id == video.id, VideoSegment.segment_index == segment_index
        )
    ).first()
    segment = existing or VideoSegment(
        video_id=video.id, segment_index=segment_index, storage_url=storage.uri(bucket, key)
    )
    segment.storage_url = storage.uri(bucket, key)
    segment.size_bytes = size_bytes or info.size
    segment.duration = duration
    segment.uploaded_at = utcnow()
    if existing is None:
        session.add(segment)
    session.flush()

    logger.info(
        "video.segment_received",
        extra={
            "video_id": str(video.id),
            "segment_index": segment_index,
            "size_bytes": segment.size_bytes,
        },
    )
    return segment


def complete_upload(
    session: Session,
    *,
    match: Match,
    expected_segments: int | None,
    storage: ObjectStorage,
    settings: Settings,
) -> Video:
    """Mark the recording complete once everything expected is present.

    Two shapes are accepted: a single master file, or a set of segments. With
    segments, the video is only complete when every index in ``0..n-1`` has
    arrived — a gap means the match is still uploading, not ready.
    """
    video = get_or_create_video(session, match=match)
    bucket = settings.storage_bucket_originals

    if expected_segments is not None:
        received = {segment.segment_index for segment in video.segments}
        missing = sorted(set(range(expected_segments)) - received)
        if missing:
            raise Conflict(
                f"{len(missing)} of {expected_segments} segments have not arrived.",
                code="SEGMENTS_INCOMPLETE",
                details={"missing": missing[:20], "expected": expected_segments},
            )
        video.size_bytes = sum(segment.size_bytes or 0 for segment in video.segments)
        # The master is assembled from segments by the pipeline's first step.
        video.original_url = None
        video.video_metadata = {
            **(video.video_metadata or {}),
            "segment_count": expected_segments,
        }
    else:
        key = keys.master_key(match.id, video.id)
        try:
            info = storage.stat(bucket, key)
        except ObjectNotFound as exc:
            raise Conflict(
                "No recording found in storage for this match.",
                code="RECORDING_MISSING",
            ) from exc
        if info.size < MIN_PLAUSIBLE_BYTES:
            raise Conflict(
                "The uploaded recording is too small to be a match.",
                code="RECORDING_TOO_SMALL",
                details={"size_bytes": info.size},
            )
        video.original_url = storage.uri(bucket, key)
        video.size_bytes = info.size

    video.status = VideoStatus.UPLOADED
    video.failure_reason = None
    _apply_retention(video, match)

    if match.status is MatchStatus.RECORDING:
        match.status = MatchStatus.UPLOADING
        match.stopped_at = match.stopped_at or utcnow()
    session.flush()

    logger.info(
        "video.upload_complete",
        extra={
            "video_id": str(video.id),
            "size_bytes": video.size_bytes,
            "segments": len(video.segments),
        },
    )
    return video


def _apply_retention(video: Video, match: Match) -> None:
    """Stamp the deletion deadline for the original from the venue's policy."""
    venue = match.field.venue
    video.purge_after = utcnow() + dt.timedelta(days=venue.video_retention_days)


# ── Processing ───────────────────────────────────────────────────────────
def mark_processing(session: Session, *, match: Match) -> Video:
    """Move a match into PROCESSING before the job is enqueued.

    Done here rather than in the worker so the UI reflects the transition
    immediately, instead of after the broker gets round to the task.
    """
    video = get_video(session, match=match)
    if video.status not in (
        VideoStatus.UPLOADED,
        VideoStatus.PROCESSING,
        VideoStatus.READY,
        VideoStatus.FAILED,
    ):
        raise Conflict(
            "This recording is not ready to be processed.",
            code="VIDEO_NOT_UPLOADED",
            details={"status": video.status.value},
        )
    if not video.original_url and not video.segments:
        raise Conflict(
            "There is nothing to process: no recording has been uploaded.",
            code="RECORDING_MISSING",
        )

    video.status = VideoStatus.PROCESSING
    video.failure_reason = None
    match.status = MatchStatus.PROCESSING
    match.failure_reason = None
    session.flush()
    return video


def delete_match_objects(
    session: Session, *, match: Match, storage: ObjectStorage, settings: Settings
) -> int:
    """Remove every stored object for a match. Used by deletion and retention.

    Derived artefacts are keyed by video id, originals by match id, so both
    prefixes are cleared.
    """
    removed = storage.delete_prefix(
        settings.storage_bucket_originals, keys.match_original_prefix(match.id)
    )
    if match.video is not None:
        removed += storage.delete_prefix(
            settings.storage_bucket_derived, keys.video_derived_prefix(match.video.id)
        )
    logger.info("match.objects_deleted", extra={"match_id": str(match.id), "objects": removed})
    return removed


def signed_playback_url(video: Video, *, storage: ObjectStorage, settings: Settings) -> str | None:
    """Short-lived URL for the replay. Buckets stay private."""
    uri = video.processed_url or video.original_url
    if not uri:
        return None
    try:
        return storage.signed_url_for_uri(uri, ttl_seconds=settings.signed_url_ttl_seconds)
    except ValueError:
        return None


def resolve_uri(uri: str | None) -> tuple[str, str] | None:
    if not uri:
        return None
    ref = parse_uri(uri)
    return ref.bucket, ref.key


def video_progress(video: Video) -> dict[str, uuid.UUID | str | int]:
    """Compact per-step state for the match page and the admin dashboard."""
    return {
        "video_id": video.id,
        "status": video.status.value,
        "segments": len(video.segments),
        "jobs": {job.step.value: job.status.value for job in video.jobs},
    }
