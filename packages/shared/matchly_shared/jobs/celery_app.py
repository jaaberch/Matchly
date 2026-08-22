"""Celery application factory.

Both workers and the API build the same app object from the same settings; the
API only ever calls ``send_task``. Task *implementations* are registered by the
worker entrypoints in ``services/``.
"""

from __future__ import annotations

import functools

from celery import Celery

from ..config import Settings, get_settings
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


def build_celery_app(settings: Settings, *, name: str = "matchly") -> Celery:
    app = Celery(name, broker=settings.broker_url, backend=settings.result_backend)
    app.conf.update(
        task_default_queue=QUEUE_DEFAULT,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # A video step can run for many minutes; acknowledge only once it is done
        # so a worker crash re-delivers the job instead of silently dropping it.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        # Results are for debugging; job state lives in `processing_jobs`.
        result_expires=60 * 60 * 24,
        task_track_started=True,
        broker_connection_retry_on_startup=True,
        task_always_eager=settings.celery_task_always_eager,
        task_eager_propagates=settings.celery_task_always_eager,
        task_routes={
            PROCESS_VIDEO: {"queue": QUEUE_VIDEO},
            RUN_STEP: {"queue": QUEUE_VIDEO},
            EXPORT_VERTICAL_CLIP: {"queue": QUEUE_VIDEO},
            PURGE_EXPIRED_VIDEOS: {"queue": QUEUE_VIDEO},
            SWEEP_STALE_CAMERAS: {"queue": QUEUE_VIDEO},
            REAP_STUCK_JOBS: {"queue": QUEUE_VIDEO},
            "matchly.ai.*": {"queue": QUEUE_AI},
        },
        beat_schedule={
            "purge-expired-videos": {
                "task": PURGE_EXPIRED_VIDEOS,
                "schedule": 60 * 60,  # hourly
            },
            "sweep-stale-cameras": {
                "task": SWEEP_STALE_CAMERAS,
                "schedule": 60,
            },
            "reap-stuck-jobs": {
                "task": REAP_STUCK_JOBS,
                "schedule": 60 * 5,
            },
        },
    )
    return app


@functools.lru_cache(maxsize=1)
def get_celery_app() -> Celery:
    """Process-wide Celery app. Call `.cache_clear()` in tests."""
    return build_celery_app(get_settings())
