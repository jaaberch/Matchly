"""Periodic housekeeping.

Three jobs that keep the platform honest between matches: return abandoned work
to the queue, tell the truth about camera liveness, and delete recordings whose
retention has run out.
"""

from __future__ import annotations

from sqlalchemy import select

from matchly_shared.config import Settings
from matchly_shared.domain import Camera, CameraStatus, Match, Video
from matchly_shared.logging import get_logger
from matchly_shared.pipeline import reap_stuck_jobs
from matchly_shared.storage import ObjectStorage, keys
from matchly_shared.timeutil import utcnow

logger = get_logger(__name__)

__all__ = ["purge_expired_videos", "reap_stuck_jobs", "sweep_stale_cameras"]


def sweep_stale_cameras(session, *, settings: Settings) -> int:
    """Flip cameras to OFFLINE once their heartbeat goes quiet.

    ``online`` is always derived from ``last_seen``, so this only keeps the
    stored column from contradicting it — an agent that dies mid-match leaves
    ``RECORDING`` behind, and a dashboard showing that indefinitely is worse
    than no dashboard.
    """
    stale = [
        camera
        for camera in session.scalars(
            select(Camera).where(Camera.status != CameraStatus.OFFLINE)
        ).all()
        if not camera.is_online(offline_after_seconds=settings.camera_offline_after_seconds)
    ]
    for camera in stale:
        camera.status = CameraStatus.OFFLINE
        logger.warning(
            "camera.marked_offline",
            extra={"camera_id": str(camera.id), "last_seen": str(camera.last_seen)},
        )
    session.commit()
    return len(stale)


def purge_expired_videos(session, *, storage: ObjectStorage, settings: Settings) -> dict:
    """Delete original recordings past their venue's retention deadline.

    Only the originals go. Generated clips are small and are what players come
    back for, so they outlive the master they were cut from — which is also why
    the two live in separate buckets.
    """
    now = utcnow()
    expired = session.scalars(
        select(Video).where(Video.purge_after.is_not(None), Video.purge_after < now)
    ).all()

    videos = objects = 0
    for video in expired:
        if not video.original_url and not video.segments:
            continue
        match = session.get(Match, video.match_id)
        if match is None:
            continue

        objects += storage.delete_prefix(
            settings.storage_bucket_originals, keys.match_original_prefix(match.id)
        )
        video.original_url = None
        video.purge_after = None
        video.video_metadata = {
            **(video.video_metadata or {}),
            "original_purged_at": now.isoformat(),
        }
        for segment in list(video.segments):
            session.delete(segment)
        videos += 1
        logger.info(
            "video.original_purged",
            extra={"video_id": str(video.id), "match_id": str(video.match_id)},
        )

    session.commit()
    return {"videos": videos, "objects": objects}
