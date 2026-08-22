"""Player check-in: the QR journey, consent, and jersey number rules.

This is the flow the whole product hangs off — if check-in data is wrong, the
pipeline attributes highlights to the wrong player.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from matchly_shared.domain import MatchPlayer, MatchStatus

MANAGER = "+212600000901"
YOUSSEF = "+212600000801"
HAMZA = "+212600000802"
MEHDI = "+212600000803"


def _join(client: TestClient, auth, match_id, phone, *, team="A", jersey=7, consent=True):
    return client.post(
        f"/api/v1/matches/{match_id}/join",
        json={"team": team, "jersey_number": jersey, "consent": consent},
        headers=auth.headers(phone),
    )


# ── The QR preview ───────────────────────────────────────────────────────
def test_preview_is_public(client: TestClient, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field, join_code="ABC123")

    # No Authorization header: a player scans this before they have an account.
    response = client.get("/api/v1/matches/join/ABC123")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["match_id"] == str(match.id)
    assert body["venue_name"] == "Arena Test Casablanca"
    assert body["field_name"] == "Pitch 1"
    assert body["joinable"] is True
    assert body["recording_disclosure"] == "This pitch is recorded."
    assert body["taken_jerseys"] == {"A": [], "B": []}


def test_preview_never_reveals_who_is_playing(client: TestClient, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field, join_code="ABC123")
    youssef = factory.user(phone=YOUSSEF, name="Youssef")
    factory.player(match=match, user=youssef, jersey_number=7)

    body = client.get("/api/v1/matches/join/ABC123")

    assert "Youssef" not in body.text
    assert body.json()["taken_jerseys"]["A"] == [7]
    assert body.json()["team_sizes"] == {"A": 1, "B": 0}


def test_preview_is_case_insensitive(client: TestClient, factory, venue_setup) -> None:
    factory.match(field=venue_setup.field, join_code="ABC123")
    assert client.get("/api/v1/matches/join/abc123").status_code == 200


def test_preview_for_an_unknown_code(client: TestClient) -> None:
    response = client.get("/api/v1/matches/join/NOPE99")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_preview_tells_a_signed_in_player_they_already_joined(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field, join_code="ABC123")
    _join(client, auth, match.id, YOUSSEF, jersey=10)

    body = client.get("/api/v1/matches/join/ABC123", headers=auth.headers(YOUSSEF)).json()

    assert body["already_joined"] is True
    assert body["my_team"] == "A"
    assert body["my_jersey_number"] == 10


# ── Joining ──────────────────────────────────────────────────────────────
def test_a_player_checks_in(client: TestClient, auth, factory, venue_setup, db: Session) -> None:
    match = factory.match(field=venue_setup.field)

    response = _join(client, auth, match.id, YOUSSEF, team="A", jersey=7)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["team"] == "A"
    assert body["jersey_number"] == 7
    assert body["is_me"] is True

    stored = db.scalars(select(MatchPlayer).where(MatchPlayer.match_id == match.id)).one()
    assert stored.consent_at is not None


def test_check_in_requires_consent(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)

    response = _join(client, auth, match.id, YOUSSEF, consent=False)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_no_row_is_written_without_consent(
    client: TestClient, auth, factory, venue_setup, db: Session
) -> None:
    match = factory.match(field=venue_setup.field)
    _join(client, auth, match.id, YOUSSEF, consent=False)

    assert db.scalars(select(MatchPlayer)).all() == []


def test_a_player_cannot_join_twice(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)
    _join(client, auth, match.id, YOUSSEF, jersey=7)

    again = _join(client, auth, match.id, YOUSSEF, jersey=8)

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ALREADY_JOINED"


def test_joining_a_match_that_has_started_is_refused(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(
        field=venue_setup.field, starts_in_hours=-0.5, status=MatchStatus.RECORDING
    )

    response = _join(client, auth, match.id, YOUSSEF)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "MATCH_NOT_JOINABLE"
    assert error["details"]["status"] == "RECORDING"


def test_check_in_is_open_during_check_in_status(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.CHECK_IN)
    assert _join(client, auth, match.id, YOUSSEF).status_code == 201


# ── Jersey numbers ───────────────────────────────────────────────────────
def test_duplicate_jersey_on_the_same_team_is_blocked(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field)
    _join(client, auth, match.id, YOUSSEF, team="A", jersey=7)

    clash = _join(client, auth, match.id, HAMZA, team="A", jersey=7)

    assert clash.status_code == 409
    error = clash.json()["error"]
    assert error["code"] == "JERSEY_TAKEN"
    assert error["details"] == {"team": "A", "jersey_number": 7}


def test_the_same_number_is_fine_on_the_other_team(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field)
    _join(client, auth, match.id, YOUSSEF, team="A", jersey=7)

    assert _join(client, auth, match.id, HAMZA, team="B", jersey=7).status_code == 201


def test_a_freed_number_can_be_reused(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)
    _join(client, auth, match.id, YOUSSEF, team="A", jersey=7)
    client.delete(f"/api/v1/matches/{match.id}/players/me", headers=auth.headers(YOUSSEF))

    assert _join(client, auth, match.id, HAMZA, team="A", jersey=7).status_code == 201


def test_simultaneous_claims_on_one_number_produce_exactly_one_winner(
    client: TestClient, auth, factory, venue_setup, db: Session
) -> None:
    """Two players tapping #7 at the same moment.

    The pre-check is racy by nature; the partial unique index is what actually
    guarantees uniqueness, and the IntegrityError it raises must surface as the
    same JERSEY_TAKEN the pre-check would have given — not a 500.
    """
    match = factory.match(field=venue_setup.field)
    # Sign both players in first, so the race is only over the insert.
    headers = [auth.headers(HAMZA), auth.headers(MEHDI)]

    def claim(header):
        return client.post(
            f"/api/v1/matches/{match.id}/join",
            json={"team": "A", "jersey_number": 7, "consent": True},
            headers=header,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, headers))

    codes = sorted(result.status_code for result in results)
    assert codes == [201, 409], [r.text for r in results]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] == "JERSEY_TAKEN"

    assert len(db.scalars(select(MatchPlayer).where(MatchPlayer.match_id == match.id)).all()) == 1


def test_jersey_number_must_be_in_range(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)

    for number in (-1, 100):
        response = _join(client, auth, match.id, YOUSSEF, jersey=number)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# ── Leaving ──────────────────────────────────────────────────────────────
def test_a_player_leaves_before_kick_off(
    client: TestClient, auth, factory, venue_setup, db: Session
) -> None:
    match = factory.match(field=venue_setup.field)
    _join(client, auth, match.id, YOUSSEF)

    response = client.delete(
        f"/api/v1/matches/{match.id}/players/me", headers=auth.headers(YOUSSEF)
    )

    assert response.status_code == 204
    assert db.scalars(select(MatchPlayer).where(MatchPlayer.match_id == match.id)).all() == []


def test_a_player_cannot_leave_once_recording_started(
    client: TestClient, auth, factory, venue_setup, db: Session
) -> None:
    from matchly_shared.domain import Match

    match = factory.match(field=venue_setup.field)
    _join(client, auth, match.id, YOUSSEF)
    db.get(Match, match.id).status = MatchStatus.RECORDING
    db.commit()

    response = client.delete(
        f"/api/v1/matches/{match.id}/players/me", headers=auth.headers(YOUSSEF)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MATCH_ALREADY_STARTED"


def test_leaving_a_match_you_are_not_in(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)

    response = client.delete(
        f"/api/v1/matches/{match.id}/players/me", headers=auth.headers(YOUSSEF)
    )

    assert response.status_code == 404


# ── Operator side ────────────────────────────────────────────────────────
def test_operator_checks_in_a_player_without_a_phone(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field)

    response = client.post(
        f"/api/v1/matches/{match.id}/players",
        json={
            "phone": "0699887766",
            "name": "Walk-in",
            "team": "B",
            "jersey_number": 9,
            "consent": True,
        },
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Walk-in"


def test_a_player_cannot_add_someone_else(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)

    response = client.post(
        f"/api/v1/matches/{match.id}/players",
        json={"phone": "0699887766", "team": "B", "jersey_number": 9, "consent": True},
        headers=auth.headers(YOUSSEF),
    )

    assert response.status_code == 403


def test_administrator_override_permits_a_duplicate_number(
    client: TestClient, auth, factory, venue_setup
) -> None:
    # Two brothers turn up in the same shirt. The venue decides it is fine; the
    # pipeline will simply not attribute those two apart.
    match = factory.match(field=venue_setup.field)
    _join(client, auth, match.id, YOUSSEF, team="A", jersey=7)

    forced = client.post(
        f"/api/v1/matches/{match.id}/players",
        json={
            "phone": "0699887766",
            "name": "Twin",
            "team": "A",
            "jersey_number": 7,
            "consent": True,
            "allow_duplicate_jersey": True,
        },
        headers=auth.headers(MANAGER),
    )

    assert forced.status_code == 201, forced.text
    assert forced.json()["jersey_override"] is True

    roster = client.get(f"/api/v1/matches/{match.id}/players", headers=auth.headers(MANAGER)).json()
    assert sorted(player["jersey_number"] for player in roster) == [7, 7]


def test_operator_corrects_a_wrong_number(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)
    player = _join(client, auth, match.id, YOUSSEF, team="A", jersey=7).json()

    response = client.patch(
        f"/api/v1/matches/{match.id}/players/{player['id']}",
        json={"jersey_number": 11},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 200
    assert response.json()["jersey_number"] == 11


def test_correcting_into_a_taken_number_is_refused(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field)
    _join(client, auth, match.id, YOUSSEF, team="A", jersey=7)
    hamza = _join(client, auth, match.id, HAMZA, team="A", jersey=10).json()

    response = client.patch(
        f"/api/v1/matches/{match.id}/players/{hamza['id']}",
        json={"jersey_number": 7},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JERSEY_TAKEN"


def test_operator_removes_a_player(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)
    player = _join(client, auth, match.id, YOUSSEF).json()

    response = client.delete(
        f"/api/v1/matches/{match.id}/players/{player['id']}", headers=auth.headers(MANAGER)
    )

    assert response.status_code == 204


# ── Roster visibility ────────────────────────────────────────────────────
def test_the_roster_shows_names_but_never_phone_numbers(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field)
    _join(client, auth, match.id, YOUSSEF, team="A", jersey=7)
    _join(client, auth, match.id, HAMZA, team="B", jersey=9)

    response = client.get(f"/api/v1/matches/{match.id}/players", headers=auth.headers(YOUSSEF))

    assert response.status_code == 200
    assert YOUSSEF not in response.text
    assert HAMZA not in response.text
    assert [player["is_me"] for player in response.json()] == [True, False]


def test_an_outsider_cannot_read_the_roster(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)
    _join(client, auth, match.id, YOUSSEF)

    response = client.get(
        f"/api/v1/matches/{match.id}/players", headers=auth.headers("+212600000999")
    )

    assert response.status_code == 403
