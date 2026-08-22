"""Matches and player check-in.

Two things here need care:

**Visibility.** A match roster says who played football where and when, so
listing is scoped by entitlement rather than by a filter the caller supplies:
admins see everything, operators see their venues, players see the matches they
joined.

**Jersey numbers.** Duplicates within a team are blocked, but a friendly
pre-check is not enough — two players can submit ``#7`` at the same moment. The
database's partial unique index is the real guarantee, and the ``IntegrityError``
it raises is translated back into the same error the pre-check would have given.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from matchly_shared.config import Settings
from matchly_shared.domain import (
    Field,
    Highlight,
    Match,
    MatchPlayer,
    MatchStatus,
    Team,
    User,
    UserRole,
    Venue,
    VenueMember,
)
from matchly_shared.logging import get_logger
from matchly_shared.timeutil import utcnow

from ..core.errors import (
    AlreadyJoined,
    Conflict,
    ConsentRequired,
    JerseyTaken,
    MatchNotJoinable,
    NotFound,
    PermissionDenied,
)
from ..core.phone import normalize_phone
from ..core.security import generate_join_code

logger = get_logger(__name__)

#: A join code must be unique. Collisions are vanishingly rare at 31^6, but a
#: retry loop is cheaper than an occasional 500.
JOIN_CODE_ATTEMPTS = 8


# ── Loading ──────────────────────────────────────────────────────────────
def _with_relations(statement: Select) -> Select:
    return statement.options(
        selectinload(Match.field).selectinload(Field.venue),
        selectinload(Match.players).selectinload(MatchPlayer.user),
        selectinload(Match.video),
    )


def get_match(session: Session, match_id: uuid.UUID) -> Match:
    match = session.scalars(_with_relations(select(Match).where(Match.id == match_id))).first()
    if match is None:
        raise NotFound("Match not found.")
    return match


def get_by_join_code(session: Session, join_code: str) -> Match:
    match = session.scalars(
        _with_relations(select(Match).where(Match.join_code == join_code.strip().upper()))
    ).first()
    if match is None:
        raise NotFound("No match has that code.")
    return match


def visible_matches_statement(user: User) -> Select:
    """Base query scoped to what the caller is entitled to see."""
    statement = _with_relations(select(Match))
    if user.role is UserRole.ADMIN:
        return statement

    # Operators see their venues' matches; every player sees the matches they joined.
    operator_venues = (
        select(Field.id)
        .join(Venue, Venue.id == Field.venue_id)
        .join(VenueMember, VenueMember.venue_id == Venue.id)
        .where(VenueMember.user_id == user.id)
    )
    joined_matches = select(MatchPlayer.match_id).where(MatchPlayer.user_id == user.id)
    return statement.where(or_(Match.field_id.in_(operator_venues), Match.id.in_(joined_matches)))


def can_view(session: Session, *, user: User, match: Match) -> bool:
    if user.role is UserRole.ADMIN:
        return True
    if any(player.user_id == user.id for player in match.players):
        return True
    return has_venue_access(session, user=user, venue_id=match.field.venue_id)


def has_venue_access(session: Session, *, user: User, venue_id: uuid.UUID) -> bool:
    if user.role is UserRole.ADMIN:
        return True
    return (
        session.scalars(
            select(VenueMember.id).where(
                VenueMember.venue_id == venue_id, VenueMember.user_id == user.id
            )
        ).first()
        is not None
    )


def require_operator_access(session: Session, *, user: User, match: Match) -> None:
    if not has_venue_access(session, user=user, venue_id=match.field.venue_id):
        raise PermissionDenied("You do not manage this venue.")


# ── Creation ─────────────────────────────────────────────────────────────
def _unique_join_code(session: Session, *, length: int) -> str:
    for _ in range(JOIN_CODE_ATTEMPTS):
        code = generate_join_code(length)
        if session.scalars(select(Match.id).where(Match.join_code == code)).first() is None:
            return code
    raise Conflict(
        "Could not allocate a join code. Please try again.",
        code="JOIN_CODE_EXHAUSTED",
    )


def create_match(session: Session, *, data, creator: User, settings: Settings) -> Match:
    field = session.get(Field, data.field_id)
    if field is None:
        raise NotFound("Field not found.")
    if not has_venue_access(session, user=creator, venue_id=field.venue_id):
        raise PermissionDenied("You do not manage this venue.")

    overlapping = session.scalars(
        select(Match).where(
            Match.field_id == field.id,
            Match.status.notin_([MatchStatus.FAILED]),
            Match.starts_at < data.ends_at,
            Match.ends_at > data.starts_at,
        )
    ).first()
    if overlapping is not None:
        # One camera per field means one match at a time; double-booking a pitch
        # would silently produce a recording attributed to the wrong match.
        raise Conflict(
            "This field already has a match booked in that window.",
            code="FIELD_DOUBLE_BOOKED",
            details={"conflicting_match_id": str(overlapping.id)},
        )

    match = Match(
        field_id=field.id,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        title=data.title,
        created_by=creator.id,
        join_code=_unique_join_code(session, length=settings.join_code_length),
        status=MatchStatus.SCHEDULED,
    )
    session.add(match)
    session.flush()
    logger.info(
        "match.created",
        extra={"match_id": str(match.id), "field_id": str(field.id), "join_code": match.join_code},
    )
    return get_match(session, match.id)


def update_match(session: Session, *, match: Match, data) -> Match:
    if match.status not in (MatchStatus.SCHEDULED, MatchStatus.CHECK_IN):
        raise Conflict(
            "A match can only be edited before it starts.",
            code="MATCH_NOT_EDITABLE",
            details={"status": match.status.value},
        )

    starts_at = data.starts_at or match.starts_at
    ends_at = data.ends_at or match.ends_at
    if ends_at <= starts_at:
        raise Conflict("ends_at must be after starts_at.", code="INVALID_TIME_WINDOW")

    match.starts_at = starts_at
    match.ends_at = ends_at
    if data.title is not None:
        match.title = data.title
    session.flush()
    return match


def delete_match(session: Session, *, match: Match) -> None:
    """Remove a match and everything attached to it.

    Database rows cascade. Stored video objects are purged by the retention job
    once Phase 3 puts objects in the buckets; until then there is nothing to
    delete in storage.
    """
    match_id = match.id
    session.delete(match)
    session.flush()
    logger.info("match.deleted", extra={"match_id": str(match_id)})


# ── Check-in ─────────────────────────────────────────────────────────────
def taken_jerseys(match: Match) -> dict[Team, list[int]]:
    taken: dict[Team, list[int]] = {Team.A: [], Team.B: []}
    for player in match.players:
        taken[player.team].append(player.jersey_number)
    return {team: sorted(numbers) for team, numbers in taken.items()}


def team_sizes(match: Match) -> dict[Team, int]:
    sizes = {Team.A: 0, Team.B: 0}
    for player in match.players:
        sizes[player.team] += 1
    return sizes


def find_player(match: Match, user_id: uuid.UUID) -> MatchPlayer | None:
    return next((player for player in match.players if player.user_id == user_id), None)


def _integrity_kind(exc: IntegrityError) -> str:
    """Which unique constraint blew up.

    PostgreSQL reports the constraint name; SQLite only names the columns, so
    both shapes are matched.
    """
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None) or ""
    message = f"{constraint} {exc.orig}".lower()
    if "match_players_user_unique" in message or ("match_id" in message and "user_id" in message):
        return "already_joined"
    if "jersey" in message:
        return "jersey_taken"
    return "unknown"


def _insert_player(
    session: Session,
    *,
    match: Match,
    user: User,
    team: Team,
    jersey_number: int,
    consent_at: dt.datetime | None,
    jersey_override: bool,
) -> MatchPlayer:
    player = MatchPlayer(
        match_id=match.id,
        user_id=user.id,
        team=team,
        jersey_number=jersey_number,
        jersey_override=jersey_override,
        consent_at=consent_at,
    )
    try:
        # A savepoint, so a constraint violation does not poison the whole
        # transaction and can be translated into a proper error.
        with session.begin_nested():
            session.add(player)
            session.flush()
    except IntegrityError as exc:
        kind = _integrity_kind(exc)
        if kind == "already_joined":
            raise AlreadyJoined() from exc
        if kind == "jersey_taken":
            raise JerseyTaken(
                f"Number {jersey_number} was just taken on team {team.value}.",
                details={"team": team.value, "jersey_number": jersey_number},
            ) from exc
        raise
    return player


def join_match(
    session: Session, *, match: Match, user: User, team: Team, jersey_number: int, consent: bool
) -> MatchPlayer:
    if not match.status.accepts_players:
        raise MatchNotJoinable(
            "This match is no longer open for check-in.",
            details={"status": match.status.value},
        )
    if not consent:
        raise ConsentRequired()
    if find_player(match, user.id) is not None:
        raise AlreadyJoined()

    # Friendly pre-check; the unique index below is what actually guarantees it.
    if jersey_number in taken_jerseys(match)[team]:
        raise JerseyTaken(
            f"Number {jersey_number} is already taken on team {team.value}.",
            details={"team": team.value, "jersey_number": jersey_number},
        )

    player = _insert_player(
        session,
        match=match,
        user=user,
        team=team,
        jersey_number=jersey_number,
        consent_at=utcnow(),
        jersey_override=False,
    )
    logger.info(
        "match.joined",
        extra={
            "match_id": str(match.id),
            "user_id": str(user.id),
            "team": team.value,
            "jersey_number": jersey_number,
        },
    )
    return player


def add_player_as_operator(session: Session, *, match: Match, data) -> MatchPlayer:
    """Check a player in from the venue's side.

    Some players turn up without a phone, or cannot scan the code. The operator
    registers them so their jersey number is still known to the pipeline; the
    account is created from the phone number they give.
    """
    if not match.status.accepts_players:
        raise MatchNotJoinable(details={"status": match.status.value})

    phone = normalize_phone(data.phone)
    user = session.scalars(
        select(User).where(User.phone == phone, User.deleted_at.is_(None))
    ).first()
    if user is None:
        user = User(name=(data.name or "").strip() or f"Player {phone[-4:]}", phone=phone)
        session.add(user)
        session.flush()

    if find_player(match, user.id) is not None:
        raise AlreadyJoined()
    if not data.allow_duplicate_jersey and data.jersey_number in taken_jerseys(match)[data.team]:
        raise JerseyTaken(
            f"Number {data.jersey_number} is already taken on team {data.team.value}.",
            details={"team": data.team.value, "jersey_number": data.jersey_number},
        )

    return _insert_player(
        session,
        match=match,
        user=user,
        team=data.team,
        jersey_number=data.jersey_number,
        consent_at=utcnow() if data.consent else None,
        jersey_override=data.allow_duplicate_jersey,
    )


def update_player(session: Session, *, match: Match, player: MatchPlayer, data) -> MatchPlayer:
    """Operator edit of a roster entry, with the administrator override."""
    team = data.team or player.team
    jersey_number = data.jersey_number if data.jersey_number is not None else player.jersey_number

    if not data.allow_duplicate_jersey:
        clash = any(
            other.id != player.id and other.team is team and other.jersey_number == jersey_number
            for other in match.players
        )
        if clash:
            raise JerseyTaken(
                f"Number {jersey_number} is already taken on team {team.value}.",
                details={"team": team.value, "jersey_number": jersey_number},
            )

    player.team = team
    player.jersey_number = jersey_number
    player.jersey_override = data.allow_duplicate_jersey

    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise JerseyTaken(
            f"Number {jersey_number} is already taken on team {team.value}.",
            details={"team": team.value, "jersey_number": jersey_number},
        ) from exc

    logger.info(
        "match.player_updated",
        extra={
            "match_id": str(match.id),
            "player_id": str(player.id),
            "jersey_override": player.jersey_override,
        },
    )
    return player


def leave_match(session: Session, *, match: Match, user: User) -> None:
    player = find_player(match, user.id)
    if player is None:
        raise NotFound("You are not in this match.")
    if not match.status.accepts_players:
        raise Conflict(
            "You cannot leave a match that has already started.",
            code="MATCH_ALREADY_STARTED",
            details={"status": match.status.value},
        )
    session.delete(player)
    session.flush()
    logger.info("match.left", extra={"match_id": str(match.id), "user_id": str(user.id)})


def remove_player(session: Session, *, match: Match, player: MatchPlayer) -> None:
    session.delete(player)
    session.flush()


# ── Listing helpers ──────────────────────────────────────────────────────
def user_matches_statement(user: User, *, scope: str) -> Select:
    statement = _with_relations(
        select(Match)
        .join(MatchPlayer, MatchPlayer.match_id == Match.id)
        .where(MatchPlayer.user_id == user.id)
    )
    now = utcnow()
    if scope == "upcoming":
        return statement.where(Match.ends_at >= now).order_by(Match.starts_at.asc())
    if scope == "past":
        return statement.where(Match.ends_at < now).order_by(Match.starts_at.desc())
    return statement.order_by(Match.starts_at.desc())


def highlight_counts(session: Session, match_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """One query for every match in the page, rather than one per row."""
    if not match_ids:
        return {}
    rows = session.execute(
        select(Highlight.match_id, func.count())
        .where(Highlight.match_id.in_(match_ids))
        .group_by(Highlight.match_id)
    ).all()
    return dict(rows)
