"""Pure check-in rules, tested without HTTP or a database session."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services.match_service import _integrity_kind, find_player, taken_jerseys, team_sizes
from matchly_shared.domain import MatchStatus, Team


def _player(*, team: Team, jersey: int, user_id: uuid.UUID | None = None):
    return SimpleNamespace(
        team=team, jersey_number=jersey, user_id=user_id or uuid.uuid4(), id=uuid.uuid4()
    )


def _match(players):
    return SimpleNamespace(players=players)


def test_taken_jerseys_are_grouped_and_sorted() -> None:
    match = _match(
        [
            _player(team=Team.A, jersey=10),
            _player(team=Team.A, jersey=4),
            _player(team=Team.B, jersey=9),
        ]
    )

    assert taken_jerseys(match) == {Team.A: [4, 10], Team.B: [9]}


def test_taken_jerseys_reports_both_teams_even_when_empty() -> None:
    # The join screen renders both columns; a missing key would crash it.
    assert taken_jerseys(_match([])) == {Team.A: [], Team.B: []}


def test_team_sizes() -> None:
    match = _match(
        [
            _player(team=Team.A, jersey=1),
            _player(team=Team.A, jersey=2),
            _player(team=Team.B, jersey=3),
        ]
    )

    assert team_sizes(match) == {Team.A: 2, Team.B: 1}


def test_find_player() -> None:
    mine = uuid.uuid4()
    match = _match([_player(team=Team.A, jersey=7, user_id=mine), _player(team=Team.B, jersey=9)])

    assert find_player(match, mine) is not None
    assert find_player(match, uuid.uuid4()) is None


# ── Status gate ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "status, joinable",
    [
        (MatchStatus.SCHEDULED, True),
        (MatchStatus.CHECK_IN, True),
        (MatchStatus.RECORDING, False),
        (MatchStatus.UPLOADING, False),
        (MatchStatus.PROCESSING, False),
        (MatchStatus.READY, False),
        (MatchStatus.FAILED, False),
    ],
)
def test_check_in_window(status: MatchStatus, joinable: bool) -> None:
    assert status.accepts_players is joinable


@pytest.mark.parametrize(
    "status, terminal",
    [(MatchStatus.READY, True), (MatchStatus.FAILED, True), (MatchStatus.RECORDING, False)],
)
def test_terminal_states(status: MatchStatus, terminal: bool) -> None:
    assert status.is_terminal is terminal


# ── Constraint translation ───────────────────────────────────────────────
class _DriverError:
    """The DBAPI error SQLAlchemy wraps: a message, and a constraint name on PostgreSQL."""

    def __init__(self, message: str, constraint: str | None) -> None:
        self._message = message
        self.diag = SimpleNamespace(constraint_name=constraint) if constraint else None

    def __str__(self) -> str:
        return self._message


class _FakeIntegrityError(Exception):
    """Stands in for SQLAlchemy's IntegrityError; only `.orig` is read."""

    def __init__(self, message: str, constraint: str | None = None) -> None:
        super().__init__(message)
        self.orig = _DriverError(message, constraint)


def test_postgres_constraint_names_are_recognised() -> None:
    # PostgreSQL reports the constraint; both unique indexes must be told apart
    # so a collision does not surface as "already joined" or a 500.
    assert (
        _integrity_kind(_FakeIntegrityError("duplicate key", "match_players_user_unique"))
        == "already_joined"
    )
    assert (
        _integrity_kind(_FakeIntegrityError("duplicate key", "match_players_jersey_key"))
        == "jersey_taken"
    )


def test_sqlite_column_lists_are_recognised() -> None:
    # SQLite names columns rather than the constraint.
    assert (
        _integrity_kind(
            _FakeIntegrityError(
                "UNIQUE constraint failed: match_players.match_id, match_players.user_id"
            )
        )
        == "already_joined"
    )
    assert (
        _integrity_kind(
            _FakeIntegrityError(
                "UNIQUE constraint failed: match_players.match_id, "
                "match_players.team, match_players.jersey_number"
            )
        )
        == "jersey_taken"
    )


def test_an_unrelated_violation_is_not_swallowed() -> None:
    # Anything else must propagate rather than be reported as a jersey clash.
    assert _integrity_kind(_FakeIntegrityError("null value in column x")) == "unknown"
