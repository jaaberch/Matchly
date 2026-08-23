"""Celery entrypoint for the computer-vision worker.

Run with::

    celery -A ai_worker.worker:app worker -Q ai,video -c 1

Kept on its own queue so a model that OOMs or hangs can never block clip
generation for a match whose highlights were already scored.

This process imports **both** step sets, so it can run a whole pipeline end to
end including detection, tracking and jersey reading. The media worker imports
only its own, which is what leaves those three PENDING there — and is what lets
this service move to a GPU node without any change to the orchestration.

Every step this worker owns is optional. If it is not running, or its model is
missing, matches still reach READY with a full replay and motion-based
highlights. The AI is an enhancement, never a dependency.
"""

from __future__ import annotations

from matchly_shared.config import get_settings
from matchly_shared.highlights import registered_detectors
from matchly_shared.logging import configure_logging, get_logger
from matchly_shared.pipeline import registered_steps

# Registering both sets is what makes this process able to run a full pipeline.
from video_worker import steps as media_steps  # noqa: F401
from video_worker import worker as media_worker

from . import steps as cv_steps  # noqa: F401

settings = get_settings()
configure_logging(level=settings.log_level, fmt=settings.log_format, service="matchly-ai-worker")
logger = get_logger(__name__)

#: The media worker's Celery app already carries every pipeline task. Serving the
#: same app here means this worker runs identical code with a richer step
#: registry, rather than a second definition that could drift.
app = media_worker.app


@app.task(name="matchly.ai.ping")
def ping() -> dict[str, object]:
    """Liveness probe, and a report of what this worker can actually do.

    Worth more than a bare "ok": the common production question is not whether
    the worker is up but whether its CV runtime loaded, and this answers it.
    """
    from sqlalchemy import text

    from matchly_shared.db import session_scope

    with session_scope() as session:
        session.execute(text("SELECT 1"))

    from .detection import available as detection_available
    from .jersey import build_recognizer

    return {
        "status": "ok",
        "worker": "ai",
        "steps": sorted(step.value for step in registered_steps()),
        "detectors": registered_detectors(),
        "detection_model": detection_available(settings.yolo_weights),
        "jersey_recognizer": build_recognizer().name,
    }
