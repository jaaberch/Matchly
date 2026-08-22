"""FastAPI application factory.

Deliberately thin: it wires middleware, error handling and routers, and does
nothing else. Domain logic lives in ``app/services``, schema in
``matchly_shared.domain``, and long-running work in the Celery workers — never in
a request handler.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from matchly_shared import __version__
from matchly_shared.config import Settings, get_settings
from matchly_shared.logging import configure_logging, get_logger

from .api.errors import register_exception_handlers
from .api.v1 import health, media
from .api.v1.router import api_router
from .core.middleware import RequestContextMiddleware
from .schemas.common import ErrorResponse

logger = get_logger(__name__)

DESCRIPTION = """
Matchly records football matches on small pitches, processes the recording, and
delivers per-player highlights.

**Authentication** — phone number plus a one-time code. Send
`POST /api/v1/auth/request-otp`, then `POST /api/v1/auth/verify-otp` to receive a
bearer token. In development the code is returned in the response as `dev_code`.
""".strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    settings.validate_for_environment()
    logger.info(
        "api.startup",
        extra={
            "environment": settings.environment,
            "storage_backend": settings.storage_backend,
            "otp_provider": settings.otp_provider,
            "version": __version__,
        },
    )
    yield
    logger.info("api.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        level=settings.log_level, fmt=settings.log_format, service=f"{settings.service_name}-api"
    )

    app = FastAPI(
        title="Matchly API",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        responses={
            401: {"model": ErrorResponse, "description": "Not authenticated"},
            422: {"model": ErrorResponse, "description": "Validation error"},
            500: {"model": ErrorResponse, "description": "Internal error"},
        },
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router)
    # Local storage stands in for the object store in development only.
    if settings.storage_backend == "local":
        app.include_router(media.router)

    return app


app = create_app()
