"""Background job infrastructure: the Celery app and the task-name contract."""

from .celery_app import build_celery_app, get_celery_app
from .task_names import (
    EXPORT_VERTICAL_CLIP,
    PROCESS_VIDEO,
    PURGE_EXPIRED_VIDEOS,
    QUEUE_AI,
    QUEUE_DEFAULT,
    QUEUE_VIDEO,
    REAP_STUCK_JOBS,
    RUN_STEP,
    SWEEP_STALE_CAMERAS,
)

__all__ = [
    "EXPORT_VERTICAL_CLIP",
    "PROCESS_VIDEO",
    "PURGE_EXPIRED_VIDEOS",
    "QUEUE_AI",
    "QUEUE_DEFAULT",
    "QUEUE_VIDEO",
    "REAP_STUCK_JOBS",
    "RUN_STEP",
    "SWEEP_STALE_CAMERAS",
    "build_celery_app",
    "get_celery_app",
]
