"""Match scheduling, listing and visibility."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from matchly_shared.domain import MatchStatus, UserRole, VenueRole

ADMIN = "+212600000900"
MANAGER = "+212600000901"
OUTSIDER = "+212600000902"
YOUSSEF = "+212600000801"


def _window(hours_ahead: float = 24, minutes: int = 60) -> dict:
    starts = dt.datetime.now(dt.UTC) + dt.timedelta(hours=hours_ahead)
    return {
        "starts_at": starts.isoformat(),
        "ends_at": (starts + dt.timedelta(minutes=minutes)).isoformat(),
    }


# ── Creation ─────────────────────────────────────────────────────────────
def test_operator_schedules_a_match(client: TestClient, auth, venue_setup) -> None:
    response = client.post(
        "/api/v1/matches",
        json={"field_id": str(venue_setup.field.id), **_window(), "title": "Friday 6-a-side"},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "Friday 6-a-side"
    assert body["status"] == "SCHEDULED"
    assert body["venue"]["name"] == "Arena Test Casablanca"
    assert body["field"]["name"] == "Pitch 1"
    assert body["players"] == []
    assert body["video_url"] is None


def test_join_codes_are_generated_and_readable(client: TestClient, auth, venue_setup) -> None:
    codes = {
        client.post(
            "/api/v1/matches",
            json={"field_id": str(venue_setup.field.id), **_window(hours_ahead=24 + index)},
            headers=auth.headers(MANAGER),
        ).json()["join_code"]
        for index in range(5)
    }

    assert len(codes) == 5
    # 0/O and 1/I/L are unreadable on a card at a noisy pitch.
    assert all(len(code) == 6 and not (set(code) & set("01OIL")) for code in codes)


def test_a_player_cannot_schedule_a_match(client: TestClient, auth, venue_setup) -> None:
    response = client.post(
        "/api/v1/matches",
        json={"field_id": str(venue_setup.field.id), **_window()},
        headers=auth.headers(OUTSIDER),
    )

    assert response.status_code == 403


def test_an_operator_cannot_book_another_venues_field(
    client: TestClient, auth, factory, venue_setup
) -> None:
    other_venue = factory.venue(name="Rival Arena", location="Rabat")
    other_field = factory.field(venue=other_venue, name="Their Pitch")

    response = client.post(
        "/api/v1/matches",
        json={"field_id": str(other_field.id), **_window()},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 403


def test_double_booking_a_field_is_refused(client: TestClient, auth, venue_setup) -> None:
    # One camera per field means one match at a time; an overlapping booking
    # would produce a recording attributed to the wrong match.
    window = _window()
    client.post(
        "/api/v1/matches",
        json={"field_id": str(venue_setup.field.id), **window},
        headers=auth.headers(MANAGER),
    )

    overlap = client.post(
        "/api/v1/matches",
        json={"field_id": str(venue_setup.field.id), **_window(hours_ahead=24.5)},
        headers=auth.headers(MANAGER),
    )

    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "FIELD_DOUBLE_BOOKED"


def test_back_to_back_matches_are_allowed(client: TestClient, auth, venue_setup) -> None:
    client.post(
        "/api/v1/matches",
        json={"field_id": str(venue_setup.field.id), **_window(hours_ahead=24)},
        headers=auth.headers(MANAGER),
    )

    next_slot = client.post(
        "/api/v1/matches",
        json={"field_id": str(venue_setup.field.id), **_window(hours_ahead=25)},
        headers=auth.headers(MANAGER),
    )

    assert next_slot.status_code == 201


def test_a_backwards_time_window_is_rejected(client: TestClient, auth, venue_setup) -> None:
    starts = dt.datetime.now(dt.UTC) + dt.timedelta(hours=24)
    response = client.post(
        "/api/v1/matches",
        json={
            "field_id": str(venue_setup.field.id),
            "starts_at": starts.isoformat(),
            "ends_at": (starts - dt.timedelta(minutes=30)).isoformat(),
        },
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_an_absurdly_long_match_is_rejected(client: TestClient, auth, venue_setup) -> None:
    response = client.post(
        "/api/v1/matches",
        json={"field_id": str(venue_setup.field.id), **_window(minutes=60 * 9)},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 422


# ── Visibility ───────────────────────────────────────────────────────────
def test_listing_is_scoped_by_entitlement(client: TestClient, auth, factory, venue_setup) -> None:
    mine = factory.match(field=venue_setup.field, starts_in_hours=24)
    other_venue = factory.venue(name="Rival Arena", location="Rabat")
    other_field = factory.field(venue=other_venue, name="Their Pitch")
    factory.match(field=other_field, starts_in_hours=25)

    admin_view = client.get("/api/v1/matches", headers=auth.headers(ADMIN)).json()
    manager_view = client.get("/api/v1/matches", headers=auth.headers(MANAGER)).json()
    player_view = client.get("/api/v1/matches", headers=auth.headers(OUTSIDER)).json()

    assert admin_view["total"] == 2
    assert [item["id"] for item in manager_view["items"]] == [str(mine.id)]
    # A player who has joined nothing sees nothing — a roster says who played
    # football where and when.
    assert player_view["total"] == 0


def test_a_player_sees_a_match_once_they_join(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field)
    client.post(
        f"/api/v1/matches/{match.id}/join",
        json={"team": "A", "jersey_number": 7, "consent": True},
        headers=auth.headers(YOUSSEF),
    )

    listed = client.get("/api/v1/matches", headers=auth.headers(YOUSSEF)).json()

    assert [item["id"] for item in listed["items"]] == [str(match.id)]


def test_filters_narrow_but_never_widen(client: TestClient, auth, factory, venue_setup) -> None:
    other_venue = factory.venue(name="Rival Arena", location="Rabat")
    other_field = factory.field(venue=other_venue, name="Their Pitch")
    factory.match(field=other_field)

    # Asking for someone else's venue returns nothing, not a 403 leak and not
    # their matches.
    response = client.get(
        f"/api/v1/matches?venue_id={other_venue.id}", headers=auth.headers(MANAGER)
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_status_filter(client: TestClient, auth, factory, venue_setup) -> None:
    factory.match(field=venue_setup.field, starts_in_hours=24)
    factory.match(field=venue_setup.field, starts_in_hours=48, status=MatchStatus.READY)

    ready = client.get("/api/v1/matches?status=READY", headers=auth.headers(MANAGER)).json()

    assert ready["total"] == 1
    assert ready["items"][0]["status"] == "READY"


def test_detail_is_visible_to_participants_and_staff(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field)
    client.post(
        f"/api/v1/matches/{match.id}/join",
        json={"team": "A", "jersey_number": 7, "consent": True},
        headers=auth.headers(YOUSSEF),
    )

    assert (
        client.get(f"/api/v1/matches/{match.id}", headers=auth.headers(YOUSSEF)).status_code == 200
    )
    assert (
        client.get(f"/api/v1/matches/{match.id}", headers=auth.headers(MANAGER)).status_code == 200
    )
    assert client.get(f"/api/v1/matches/{match.id}", headers=auth.headers(ADMIN)).status_code == 200


def test_detail_is_refused_to_everyone_else(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)

    response = client.get(f"/api/v1/matches/{match.id}", headers=auth.headers(OUTSIDER))

    assert response.status_code == 403


def test_venue_dashboard_query(client: TestClient, auth, factory, venue_setup) -> None:
    today = factory.match(field=venue_setup.field, starts_in_hours=2)
    factory.match(field=venue_setup.field, starts_in_hours=72)

    day = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)).date().isoformat()
    response = client.get(
        f"/api/v1/venues/{venue_setup.venue.id}/matches?date={day}",
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(today.id)]


def test_venue_dashboard_is_venue_scoped(client: TestClient, auth, venue_setup) -> None:
    response = client.get(
        f"/api/v1/venues/{venue_setup.venue.id}/matches", headers=auth.headers(OUTSIDER)
    )

    assert response.status_code == 403


# ── My matches ───────────────────────────────────────────────────────────
def test_my_matches_splits_upcoming_from_past(
    client: TestClient, auth, factory, venue_setup
) -> None:
    from matchly_shared.domain import User

    upcoming = factory.match(field=venue_setup.field, starts_in_hours=24)
    played = factory.match(field=venue_setup.field, starts_in_hours=-48, status=MatchStatus.READY)
    youssef = factory.user(phone=YOUSSEF, name="Youssef")
    factory.player(match=upcoming, user=youssef, jersey_number=7)
    factory.player(match=played, user=youssef, jersey_number=7)
    assert isinstance(youssef, User)

    headers = auth.headers(YOUSSEF)
    all_matches = client.get("/api/v1/users/me/matches", headers=headers).json()
    next_up = client.get("/api/v1/users/me/matches?scope=upcoming", headers=headers).json()
    history = client.get("/api/v1/users/me/matches?scope=past", headers=headers).json()

    assert all_matches["total"] == 2
    assert [item["id"] for item in next_up["items"]] == [str(upcoming.id)]
    assert [item["id"] for item in history["items"]] == [str(played.id)]


def test_my_matches_is_empty_for_a_new_player(client: TestClient, auth) -> None:
    assert (
        client.get("/api/v1/users/me/matches", headers=auth.headers(OUTSIDER)).json()["total"] == 0
    )


# ── Editing and deletion ─────────────────────────────────────────────────
def test_operator_reschedules_a_match(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)
    moved = _window(hours_ahead=48)

    response = client.patch(
        f"/api/v1/matches/{match.id}",
        json={**moved, "title": "Moved"},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Moved"


def test_a_started_match_cannot_be_rescheduled(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)

    response = client.patch(
        f"/api/v1/matches/{match.id}", json={"title": "Nope"}, headers=auth.headers(MANAGER)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MATCH_NOT_EDITABLE"


def test_deleting_a_match_removes_its_roster(
    client: TestClient, auth, factory, venue_setup, db
) -> None:
    from sqlalchemy import select

    from matchly_shared.domain import MatchPlayer

    match = factory.match(field=venue_setup.field)
    client.post(
        f"/api/v1/matches/{match.id}/join",
        json={"team": "A", "jersey_number": 7, "consent": True},
        headers=auth.headers(YOUSSEF),
    )

    response = client.delete(f"/api/v1/matches/{match.id}", headers=auth.headers(MANAGER))

    assert response.status_code == 204
    assert db.scalars(select(MatchPlayer).where(MatchPlayer.match_id == match.id)).all() == []


def test_a_player_cannot_delete_a_match(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)
    client.post(
        f"/api/v1/matches/{match.id}/join",
        json={"team": "A", "jersey_number": 7, "consent": True},
        headers=auth.headers(YOUSSEF),
    )

    response = client.delete(f"/api/v1/matches/{match.id}", headers=auth.headers(YOUSSEF))

    assert response.status_code == 403


def test_plain_operators_can_still_run_matches(
    client: TestClient, auth, factory, venue_setup
) -> None:
    # OPERATOR is enough for day-to-day match work; only venue settings and staff
    # need MANAGER.
    desk = factory.user(phone=OUTSIDER, name="Desk staff", role=UserRole.VENUE_OPERATOR)
    factory.member(venue=venue_setup.venue, user=desk, role=VenueRole.OPERATOR)

    response = client.post(
        "/api/v1/matches",
        json={"field_id": str(venue_setup.field.id), **_window()},
        headers=auth.headers(OUTSIDER),
    )

    assert response.status_code == 201
