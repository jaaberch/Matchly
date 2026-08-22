"""v1 router aggregation.

Routers are added here as each phase lands, so ``/docs`` only ever advertises
endpoints that actually work.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import auth, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)

# Phase 2+: matches, venues, cameras, videos, highlights, admin.
