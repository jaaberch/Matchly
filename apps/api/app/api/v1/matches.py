"""Matches and player check-in."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from matchly_shared.domain import Field, Match, MatchStatus

from ...core.errors import NotFound, PermissionDenied
from ...core.pagination import Page, PageParams, PageParamsDep, build_page, paginate
from ...schemas.match import (
    MatchCreate,
    MatchDetail,
    MatchJoinIn,
    MatchJoinPreview,
    MatchPlayerCreate,
    MatchPlayerOut,
    MatchPlayerUpdate,
    MatchSummary,
    MatchUpdate,
)
from ...services import match_service
from ..deps import CurrentUser, OptionalUser, SessionDep, SettingsDep
from .presenters import match_detail, match_summary, player_out

router = APIRouter(prefix="/matches", tags=["matches"])


def _page_of_matches(session, rows, total, params: PageParams) -> dict:
    counts = match_service.highlight_counts(session, [match.id for match in rows])
    items = [match_summary(match, highlight_count=counts.get(match.id, 0)) for match in rows]
    return build_page(items, total, params)


# ── Listing ──────────────────────────────────────────────────────────────
@router.get(
    "",
    response_model=Page[MatchSummary],
    summary="List matches you can see",
    description=(
        "Scoped by entitlement: platform admins see every match, venue staff see "
        "their venues' matches, and players see the matches they joined. Filters "
        "narrow within that — they never widen it."
    ),
)
def list_matches(
    session: SessionDep,
    user: CurrentUser,
    params: PageParamsDep,
    venue_id: uuid.UUID | None = None,
    field_id: uuid.UUID | None = None,
    match_status: Annotated[MatchStatus | None, Query(alias="status")] = None,
    date_from: Annotated[dt.datetime | None, Query(alias="from")] = None,
    date_to: Annotated[dt.datetime | None, Query(alias="to")] = None,
) -> dict:
    statement = match_service.visible_matches_statement(user)
    if venue_id is not None:
        statement = statement.where(
            Match.field_id.in_(select(Field.id).where(Field.venue_id == venue_id))
        )
    if field_id is not None:
        statement = statement.where(Match.field_id == field_id)
    if match_status is not None:
        statement = statement.where(Match.status == match_status)
    if date_from is not None:
        statement = statement.where(Match.starts_at >= date_from)
    if date_to is not None:
        statement = statement.where(Match.starts_at <= date_to)

    rows, total = paginate(session, statement.order_by(Match.starts_at.desc()), params)
    return _page_of_matches(session, rows, total, params)


@router.post(
    "",
    response_model=MatchDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a match",
    responses={409: {"description": "The field is already booked in that window"}},
)
def create_match(
    payload: MatchCreate, session: SessionDep, settings: SettingsDep, user: CurrentUser
) -> MatchDetail:
    match = match_service.create_match(session, data=payload, creator=user, settings=settings)
    return match_detail(match, viewer_id=user.id)


# ── Check-in preview (public: this is the QR code target) ────────────────
@router.get(
    "/join/{join_code}",
    response_model=MatchJoinPreview,
    summary="Check-in preview for a QR code",
    description=(
        "Public, because a player scans this before signing in. It carries no "
        "player identities — only which numbers are taken, which is all that is "
        "needed to pick one."
    ),
)
def join_preview(join_code: str, session: SessionDep, user: OptionalUser) -> MatchJoinPreview:
    match = match_service.get_by_join_code(session, join_code)
    mine = match_service.find_player(match, user.id) if user else None
    return MatchJoinPreview(
        match_id=match.id,
        title=match.title,
        status=match.status,
        starts_at=match.starts_at,
        ends_at=match.ends_at,
        venue_name=match.field.venue.name,
        field_name=match.field.name,
        recording_disclosure=match.field.venue.recording_disclosure,
        joinable=match.status.accepts_players,
        taken_jerseys=match_service.taken_jerseys(match),
        team_sizes=match_service.team_sizes(match),
        already_joined=mine is not None,
        my_team=mine.team if mine else None,
        my_jersey_number=mine.jersey_number if mine else None,
    )


# ── Single match ─────────────────────────────────────────────────────────
@router.get("/{match_id}", response_model=MatchDetail, summary="Match detail")
def get_match(match_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> MatchDetail:
    match = match_service.get_match(session, match_id)
    if not match_service.can_view(session, user=user, match=match):
        raise PermissionDenied("You do not have access to this match.")
    counts = match_service.highlight_counts(session, [match.id])
    return match_detail(match, viewer_id=user.id, highlight_count=counts.get(match.id, 0))


@router.patch("/{match_id}", response_model=MatchDetail, summary="Reschedule or rename a match")
def update_match(
    match_id: uuid.UUID, payload: MatchUpdate, session: SessionDep, user: CurrentUser
) -> MatchDetail:
    match = match_service.get_match(session, match_id)
    match_service.require_operator_access(session, user=user, match=match)
    return match_detail(
        match_service.update_match(session, match=match, data=payload), viewer_id=user.id
    )


@router.delete(
    "/{match_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a match and its recordings",
)
def delete_match(match_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    match = match_service.get_match(session, match_id)
    match_service.require_operator_access(session, user=user, match=match)
    match_service.delete_match(session, match=match)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Roster ───────────────────────────────────────────────────────────────
@router.post(
    "/{match_id}/join",
    response_model=MatchPlayerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Check in to a match",
    responses={
        409: {"description": "JERSEY_TAKEN, ALREADY_JOINED or MATCH_NOT_JOINABLE"},
        422: {"description": "CONSENT_REQUIRED"},
    },
)
def join_match(
    match_id: uuid.UUID, payload: MatchJoinIn, session: SessionDep, user: CurrentUser
) -> MatchPlayerOut:
    match = match_service.get_match(session, match_id)
    player = match_service.join_match(
        session,
        match=match,
        user=user,
        team=payload.team,
        jersey_number=payload.jersey_number,
        consent=payload.consent,
    )
    player.user = user
    return player_out(player, viewer_id=user.id)


@router.delete(
    "/{match_id}/players/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Leave a match before it starts",
)
def leave_match(match_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    match = match_service.get_match(session, match_id)
    match_service.leave_match(session, match=match, user=user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{match_id}/players", response_model=list[MatchPlayerOut], summary="Match roster")
def list_players(
    match_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[MatchPlayerOut]:
    match = match_service.get_match(session, match_id)
    if not match_service.can_view(session, user=user, match=match):
        raise PermissionDenied("You do not have access to this match.")
    players = sorted(match.players, key=lambda p: (p.team.value, p.jersey_number))
    return [player_out(player, viewer_id=user.id) for player in players]


@router.post(
    "/{match_id}/players",
    response_model=MatchPlayerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Check a player in from the venue side",
    description=(
        "For players who turn up without a phone. Venue staff only. "
        "`allow_duplicate_jersey` is the administrator override."
    ),
)
def add_player(
    match_id: uuid.UUID, payload: MatchPlayerCreate, session: SessionDep, user: CurrentUser
) -> MatchPlayerOut:
    match = match_service.get_match(session, match_id)
    match_service.require_operator_access(session, user=user, match=match)
    player = match_service.add_player_as_operator(session, match=match, data=payload)
    return player_out(player, viewer_id=user.id)


@router.patch(
    "/{match_id}/players/{player_id}",
    response_model=MatchPlayerOut,
    summary="Correct a player's team or jersey number",
    description="Venue staff only. Set `allow_duplicate_jersey` to override the per-team rule.",
)
def update_player(
    match_id: uuid.UUID,
    player_id: uuid.UUID,
    payload: MatchPlayerUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> MatchPlayerOut:
    match = match_service.get_match(session, match_id)
    match_service.require_operator_access(session, user=user, match=match)
    player = next((p for p in match.players if p.id == player_id), None)
    if player is None:
        raise NotFound("That player is not in this match.")
    return player_out(
        match_service.update_player(session, match=match, player=player, data=payload),
        viewer_id=user.id,
    )


@router.delete(
    "/{match_id}/players/{player_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a player from the roster",
)
def remove_player(
    match_id: uuid.UUID, player_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Response:
    match = match_service.get_match(session, match_id)
    match_service.require_operator_access(session, user=user, match=match)
    player = next((p for p in match.players if p.id == player_id), None)
    if player is None:
        raise NotFound("That player is not in this match.")
    match_service.remove_player(session, match=match, player=player)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Venue dashboard query ────────────────────────────────────────────────
venue_matches_router = APIRouter(prefix="/venues", tags=["matches"])


@venue_matches_router.get(
    "/{venue_id}/matches",
    response_model=Page[MatchSummary],
    summary="Matches at a venue",
    description="The venue dashboard's main query. `date` filters to a single local day.",
)
def venue_matches(
    venue_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    params: PageParamsDep,
    date: dt.date | None = None,
    match_status: Annotated[MatchStatus | None, Query(alias="status")] = None,
) -> dict:
    if not match_service.has_venue_access(session, user=user, venue_id=venue_id):
        raise PermissionDenied("You do not have access to this venue.")

    statement = match_service.visible_matches_statement(user).where(
        Match.field_id.in_(select(Field.id).where(Field.venue_id == venue_id))
    )
    if date is not None:
        day_start = dt.datetime.combine(date, dt.time.min, tzinfo=dt.UTC)
        statement = statement.where(
            Match.starts_at >= day_start, Match.starts_at < day_start + dt.timedelta(days=1)
        )
    if match_status is not None:
        statement = statement.where(Match.status == match_status)

    rows, total = paginate(session, statement.order_by(Match.starts_at.asc()), params)
    return _page_of_matches(session, rows, total, params)


# ── Player's own matches ─────────────────────────────────────────────────
me_router = APIRouter(prefix="/users/me", tags=["matches"])


@me_router.get(
    "/matches",
    response_model=Page[MatchSummary],
    summary="Matches you have joined",
)
def my_matches(
    session: SessionDep,
    user: CurrentUser,
    params: PageParamsDep,
    scope: Literal["all", "upcoming", "past"] = "all",
) -> dict:
    statement = match_service.user_matches_statement(user, scope=scope)
    rows, total = paginate(session, statement, params)
    return _page_of_matches(session, rows, total, params)
