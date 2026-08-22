"""v1 router aggregation.

Routers are added here as each phase lands, so ``/docs`` only ever advertises
endpoints that actually work.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import auth, cameras, matches, users, venues

api_router = APIRouter(prefix="/api/v1")

# Phase 1
api_router.include_router(auth.router)
api_router.include_router(users.router)

# Phase 2
api_router.include_router(venues.router)
api_router.include_router(venues.fields_router)
api_router.include_router(cameras.router)
api_router.include_router(matches.router)
api_router.include_router(matches.venue_matches_router)
api_router.include_router(matches.me_router)

# Phase 3+: videos, highlights, admin.
