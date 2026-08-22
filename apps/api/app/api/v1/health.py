"""Liveness and readiness.

``/health`` must never touch a dependency: it answers "is this process alive", which
is what a container orchestrator restarts on. ``/health/ready`` checks Postgres and
Redis, which is what a load balancer should gate traffic on.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from matchly_shared import __version__
from matchly_shared.logging import get_logger

from ...schemas.common import HealthResponse, ReadinessResponse
from ..deps import SessionDep, SettingsDep

logger = get_logger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness")
def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=__version__,
        environment=settings.environment,
    )


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness")
def readiness(session: SessionDep, settings: SettingsDep, response: Response) -> ReadinessResponse:
    checks: dict[str, str] = {}

    try:
        session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - exercised only when PG is down
        logger.error("health.database_unavailable", exc_info=exc)
        checks["database"] = "unavailable"

    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        client.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # pragma: no cover - exercised only when Redis is down
        logger.error("health.redis_unavailable", exc_info=exc)
        checks["redis"] = "unavailable"

    ready = all(value == "ok" for value in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ready else "degraded", checks=checks)
