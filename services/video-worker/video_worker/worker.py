"""Celery entrypoint for the video worker.

Run with::

    celery -A video_worker.worker:app worker -Q video -c 2

Phase 1 registers only a health task, so the compose stack boots and the worker's
broker/database connectivity can be verified before any pipeline code exists.
Phases 3–4 add the real steps: probe, transcode, sample, clip, thumbnail, persist.
"""

from __future__ import annotations

from matchly_shared.config import get_settings
from matchly_shared.jobs import build_celery_app
from matchly_shared.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(level=settings.log_level, fmt=settings.log_format, service="matchly-video-worker")
logger = get_logger(__name__)

app = build_celery_app(settings, name="matchly-video-worker")


@app.task(name="matchly.video.ping")
def ping() -> dict[str, str]:
    """Liveness probe: proves the worker has a broker and a database."""
    from sqlalchemy import text

    from matchly_shared.db import session_scope

    with session_scope() as session:
        session.execute(text("SELECT 1"))
    logger.info("video_worker.ping")
    return {"status": "ok", "worker": "video"}
