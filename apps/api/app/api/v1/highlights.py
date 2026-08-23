"""Highlight delivery.

Clips are private. Every URL returned here is a short-lived signed link minted
after the caller has been authorised — there is no permanent public URL for any
match video, which is what keeps a shared clip from becoming a shared archive.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from matchly_shared.domain import Highlight, Match, MatchPlayer

from ...core.errors import PermissionDenied
from ...core.pagination import Page, PageParamsDep, build_page, paginate
from ...schemas.highlight import HighlightOut, HighlightPlayerRef, MatchHighlightsOut
from ...services import match_service
from ..deps import CurrentUser, SessionDep, SettingsDep, StorageDep

router = APIRouter(tags=["highlights"])


def _highlight_out(highlight: Highlight, *, storage, settings) -> HighlightOut:
    def sign(uri: str | None) -> str | None:
        try:
            return storage.signed_url_for_uri(uri, ttl_seconds=settings.signed_url_ttl_seconds)
        except ValueError:
            return None

    player = highlight.player
    return HighlightOut(
        id=highlight.id,
        match_id=highlight.match_id,
        start_time=highlight.start_time,
        end_time=highlight.end_time,
        duration=highlight.duration,
        score=highlight.score,
        type=highlight.type,
        signals=highlight.signals or {},
        video_url=sign(highlight.video_url),
        video_url_vertical=sign(highlight.video_url_vertical),
        thumbnail_url=sign(highlight.thumbnail_url),
        player=(
            HighlightPlayerRef(
                id=player.id,
                name=player.user.name,
                team=player.team,
                jersey_number=player.jersey_number,
            )
            if player
            else None
        ),
        created_at=highlight.created_at,
    )


@router.get(
    "/matches/{match_id}/highlights",
    response_model=MatchHighlightsOut,
    summary="Highlights from a match",
    description=(
        "Ordered by when they happened, not by score, so the reel plays as the "
        "match did. `player_id` narrows it to one player's personal cut."
    ),
)
def match_highlights(
    match_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: CurrentUser,
    player_id: Annotated[uuid.UUID | None, Query(description="Filter to one player")] = None,
    mine: Annotated[bool, Query(description="Only highlights attributed to you")] = False,
) -> MatchHighlightsOut:
    match = match_service.get_match(session, match_id)
    if not match_service.can_view(session, user=user, match=match):
        raise PermissionDenied("You do not have access to this match.")

    statement = (
        select(Highlight)
        .where(Highlight.match_id == match_id)
        .options(selectinload(Highlight.player).selectinload(MatchPlayer.user))
        .order_by(Highlight.start_time)
    )
    if mine:
        me = match_service.find_player(match, user.id)
        # A player with no attributed clips gets an empty list, not everyone's.
        statement = statement.where(Highlight.player_id == (me.id if me else uuid.UUID(int=0)))
    elif player_id is not None:
        statement = statement.where(Highlight.player_id == player_id)

    rows = session.scalars(statement).all()
    return MatchHighlightsOut(
        match_id=match_id,
        match_title=match.title,
        total=len(rows),
        items=[_highlight_out(row, storage=storage, settings=settings) for row in rows],
    )


me_router = APIRouter(prefix="/users/me", tags=["highlights"])


@me_router.get(
    "/highlights",
    response_model=Page[HighlightOut],
    summary="Your highlights across every match",
    description="Newest first. Only clips attributed to you by jersey recognition.",
)
def my_highlights(
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: CurrentUser,
    params: PageParamsDep,
) -> dict:
    statement = (
        select(Highlight)
        .join(MatchPlayer, MatchPlayer.id == Highlight.player_id)
        .join(Match, Match.id == Highlight.match_id)
        .where(MatchPlayer.user_id == user.id)
        .options(selectinload(Highlight.player).selectinload(MatchPlayer.user))
        .order_by(Match.starts_at.desc(), Highlight.start_time)
    )
    rows, total = paginate(session, statement, params)
    return build_page(
        [_highlight_out(row, storage=storage, settings=settings) for row in rows], total, params
    )
