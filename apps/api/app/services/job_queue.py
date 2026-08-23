"""Enqueuing background work.

One indirection between the routes and Celery, for two reasons. A broker outage
should surface as a clear 503 rather than a 30-second hang followed by a 500 —
the operator needs to know the recording is safe and only the *processing* is
delayed. And tests get one place to intercept, instead of patching Celery.

The API enqueues by task name and imports no worker code, so this module never
pulls ffmpeg or any CV dependency into the API image.
"""

from __future__ import annotations

import uuid

from matchly_shared.jobs import EXPORT_VERTICAL_CLIP, PROCESS_VIDEO, RUN_STEP, get_celery_app
from matchly_shared.logging import get_logger

from ..core.errors import AppError

logger = get_logger(__name__)


class QueueUnavailable(AppError):
    code = "QUEUE_UNAVAILABLE"
    status_code = 503
    message = (
        "Processing could not be queued right now. The recording is safe — try again in a moment."
    )


def _send(name: str, **kwargs) -> str:
    try:
        return get_celery_app().send_task(name, kwargs=kwargs).id
    except Exception as exc:  # kombu raises a wide range for broker trouble
        logger.error("queue.enqueue_failed", extra={"task": name, "error": str(exc)[:200]})
        raise QueueUnavailable() from exc


def enqueue_processing(video_id: uuid.UUID, *, force: bool = False) -> str:
    return _send(PROCESS_VIDEO, video_id=str(video_id), force=force)


def enqueue_step(video_id: uuid.UUID, *, step: str, force: bool = True) -> str:
    """Re-run a single pipeline step. Backs the admin retry action."""
    return _send(RUN_STEP, video_id=str(video_id), step=step, force=force)


def enqueue_vertical_export(highlight_id: uuid.UUID) -> str:
    return _send(EXPORT_VERTICAL_CLIP, highlight_id=str(highlight_id))
