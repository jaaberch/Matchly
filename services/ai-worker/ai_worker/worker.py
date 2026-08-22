"""Celery entrypoint for the AI worker.

Run with::

    celery -A ai_worker.worker:app worker -Q ai -c 1

Kept on its own queue so a model that OOMs or hangs can never block clip
generation for a match whose highlights were already scored. Every step this
worker owns is skippable: if it is down, matches still reach READY with a full
replay and motion-based highlights.
"""

from __future__ import annotations

from matchly_shared.config import get_settings
from matchly_shared.jobs import build_celery_app
from matchly_shared.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(level=settings.log_level, fmt=settings.log_format, service="matchly-ai-worker")
logger = get_logger(__name__)

app = build_celery_app(settings, name="matchly-ai-worker")


@app.task(name="matchly.ai.ping")
def ping() -> dict[str, str]:
    """Liveness probe: proves the worker has a broker and a database."""
    from sqlalchemy import text

    from matchly_shared.db import session_scope

    with session_scope() as session:
        session.execute(text("SELECT 1"))
    logger.info("ai_worker.ping")
    return {"status": "ok", "worker": "ai"}
