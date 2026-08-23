"""Celery entrypoint for the video worker.

Run with::

    celery -A video_worker.worker:app worker -Q video -c 2

Importing ``video_worker.steps`` is what registers the pipeline steps this
process can execute. The runner does the rest; these tasks are thin wrappers that
own only the Celery concerns — retries, and turning a task argument into a
database session.
"""

from __future__ import annotations

import uuid

from matchly_shared.config import get_settings
from matchly_shared.db import session_scope
from matchly_shared.domain import JobStep
from matchly_shared.jobs import build_celery_app
from matchly_shared.jobs.task_names import (
    EXPORT_VERTICAL_CLIP,
    PROCESS_VIDEO,
    PURGE_EXPIRED_VIDEOS,
    REAP_STUCK_JOBS,
    RUN_STEP,
    SWEEP_STALE_CAMERAS,
)
from matchly_shared.logging import bind_log_context, configure_logging, get_logger
from matchly_shared.pipeline import reap_stuck_jobs as reap
from matchly_shared.pipeline import run_pipeline
from matchly_shared.storage import get_storage

from . import maintenance, steps  # noqa: F401  (steps imported for registration)

settings = get_settings()
configure_logging(level=settings.log_level, fmt=settings.log_format, service="matchly-video-worker")
logger = get_logger(__name__)

app = build_celery_app(settings, name="matchly-video-worker")


@app.task(name="matchly.video.ping")
def ping() -> dict[str, str]:
    """Liveness probe: proves the worker has a broker and a database."""
    from sqlalchemy import text

    with session_scope() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ok", "worker": "video", "steps": len(steps.__all__)}


@app.task(
    name=PROCESS_VIDEO,
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def process_video(self, video_id: str, force: bool = False) -> dict:
    """Run the pipeline for one recording.

    Step-level state lives in ``processing_jobs``, so a retry resumes at the step
    that failed rather than re-transcoding an hour of 4K from the top.
    """
    token = bind_log_context(video_id=video_id, task_id=self.request.id)
    try:
        with session_scope() as session:
            result = run_pipeline(
                session,
                video_id=uuid.UUID(video_id),
                settings=get_settings(),
                storage=get_storage(),
                force=force,
            )
        logger.info("pipeline.finished", extra=result.as_dict())
        return result.as_dict()
    finally:
        from matchly_shared.logging import reset_log_context

        reset_log_context(token)


@app.task(name=RUN_STEP, bind=True, max_retries=2)
def run_step(self, video_id: str, step: str, force: bool = True) -> dict:
    """Re-run a single step. Backs the admin dashboard's retry action."""
    with session_scope() as session:
        result = run_pipeline(
            session,
            video_id=uuid.UUID(video_id),
            settings=get_settings(),
            storage=get_storage(),
            force=force,
            only=JobStep(step),
        )
    return result.as_dict()


@app.task(name=EXPORT_VERTICAL_CLIP)
def export_vertical_clip(highlight_id: str) -> dict:
    """Generate a 9:16 export on demand, for a clip that has none yet."""
    from .exports import export_vertical

    with session_scope() as session:
        return export_vertical(
            session,
            highlight_id=uuid.UUID(highlight_id),
            storage=get_storage(),
            settings=get_settings(),
        )


# ── Maintenance (celery beat) ────────────────────────────────────────────
@app.task(name=REAP_STUCK_JOBS)
def reap_stuck_jobs_task() -> dict:
    with session_scope() as session:
        return {"reaped": reap(session)}


@app.task(name=SWEEP_STALE_CAMERAS)
def sweep_stale_cameras_task() -> dict:
    with session_scope() as session:
        return {"marked_offline": maintenance.sweep_stale_cameras(session, settings=get_settings())}


@app.task(name=PURGE_EXPIRED_VIDEOS)
def purge_expired_videos_task() -> dict:
    with session_scope() as session:
        return maintenance.purge_expired_videos(
            session, storage=get_storage(), settings=get_settings()
        )
