"""Venue, field and camera management, and the permissions around them."""

from __future__ import annotations

from fastapi.testclient import TestClient

from matchly_shared.domain import UserRole, VenueRole

ADMIN = "+212600000900"
MANAGER = "+212600000901"
OUTSIDER = "+212600000902"


# ── Venues ───────────────────────────────────────────────────────────────
def test_admin_creates_a_venue(client: TestClient, auth, factory) -> None:
    factory.user(phone=ADMIN, name="Admin", role=UserRole.ADMIN)

    response = client.post(
        "/api/v1/venues",
        json={
            "name": "Arena Demo Casablanca",
            "location": "Boulevard Zerktouni",
            "recording_disclosure": "This pitch is recorded.",
        },
        headers=auth.headers(ADMIN),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Arena Demo Casablanca"
    assert body["timezone"] == "Africa/Casablanca"
    assert body["video_retention_days"] == 90  # from the platform default


def test_a_player_cannot_create_a_venue(client: TestClient, auth) -> None:
    response = client.post(
        "/api/v1/venues",
        json={"name": "Rogue Arena", "location": "Nowhere"},
        headers=auth.headers(OUTSIDER),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_an_operator_cannot_create_a_venue(client: TestClient, auth, venue_setup) -> None:
    # Operators run venues; only the platform onboards new ones.
    response = client.post(
        "/api/v1/venues",
        json={"name": "Second Arena", "location": "Rabat"},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 403


def test_operators_only_list_their_own_venues(
    client: TestClient, auth, factory, venue_setup
) -> None:
    factory.venue(name="Someone Else's Arena", location="Marrakech")

    mine = client.get("/api/v1/venues", headers=auth.headers(MANAGER)).json()
    everything = client.get("/api/v1/venues", headers=auth.headers(ADMIN)).json()

    assert [item["name"] for item in mine["items"]] == ["Arena Test Casablanca"]
    assert mine["total"] == 1
    assert everything["total"] == 2


def test_players_cannot_list_venues(client: TestClient, auth, venue_setup) -> None:
    assert client.get("/api/v1/venues", headers=auth.headers(OUTSIDER)).status_code == 403


def test_venue_detail_includes_fields_and_camera(client: TestClient, auth, venue_setup) -> None:
    response = client.get(f"/api/v1/venues/{venue_setup.venue.id}", headers=auth.headers(MANAGER))

    assert response.status_code == 200
    body = response.json()
    assert len(body["fields"]) == 1
    field = body["fields"][0]
    assert field["name"] == "Pitch 1"
    # Field.camera_id is exposed from the relationship, not stored on the field.
    assert field["camera_id"] == str(venue_setup.camera.id)
    assert field["camera"]["online"] is False  # never sent a heartbeat


def test_venue_detail_never_leaks_the_camera_credentials(
    client: TestClient, auth, venue_setup
) -> None:
    body = client.get(f"/api/v1/venues/{venue_setup.venue.id}", headers=auth.headers(MANAGER)).text

    assert "camera-secret" not in body
    assert "token_hash" not in body
    assert "stream_url" not in body


def test_a_non_member_cannot_read_a_venue(client: TestClient, auth, venue_setup) -> None:
    response = client.get(f"/api/v1/venues/{venue_setup.venue.id}", headers=auth.headers(OUTSIDER))

    assert response.status_code == 403


def test_manager_updates_retention_policy(client: TestClient, auth, venue_setup) -> None:
    response = client.patch(
        f"/api/v1/venues/{venue_setup.venue.id}",
        json={"video_retention_days": 30},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 200
    assert response.json()["video_retention_days"] == 30


def test_a_plain_operator_cannot_change_venue_settings(
    client: TestClient, auth, factory, venue_setup
) -> None:
    operator = factory.user(phone=OUTSIDER, name="Desk staff", role=UserRole.VENUE_OPERATOR)
    factory.member(venue=venue_setup.venue, user=operator, role=VenueRole.OPERATOR)

    response = client.patch(
        f"/api/v1/venues/{venue_setup.venue.id}",
        json={"video_retention_days": 1},
        headers=auth.headers(OUTSIDER),
    )

    assert response.status_code == 403


# ── Staff ────────────────────────────────────────────────────────────────
def test_manager_grants_access_by_phone(client: TestClient, auth, venue_setup) -> None:
    response = client.post(
        f"/api/v1/venues/{venue_setup.venue.id}/members",
        json={"phone": "0655001122", "name": "Nouveau", "role": "OPERATOR"},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Nouveau"
    assert response.json()["role"] == "OPERATOR"

    members = client.get(
        f"/api/v1/venues/{venue_setup.venue.id}/members", headers=auth.headers(MANAGER)
    ).json()
    assert {member["name"] for member in members} == {"Arena Manager", "Nouveau"}


def test_granting_access_twice_updates_the_role(client: TestClient, auth, venue_setup) -> None:
    url = f"/api/v1/venues/{venue_setup.venue.id}/members"
    client.post(
        url, json={"phone": "0655001122", "role": "OPERATOR"}, headers=auth.headers(MANAGER)
    )
    response = client.post(
        url, json={"phone": "0655001122", "role": "MANAGER"}, headers=auth.headers(MANAGER)
    )

    assert response.status_code == 201
    assert response.json()["role"] == "MANAGER"
    assert len(client.get(url, headers=auth.headers(MANAGER)).json()) == 2


def test_a_newly_granted_operator_can_sign_in_and_see_the_venue(
    client: TestClient, auth, venue_setup
) -> None:
    client.post(
        f"/api/v1/venues/{venue_setup.venue.id}/members",
        json={"phone": "0655001122", "name": "Nouveau"},
        headers=auth.headers(MANAGER),
    )

    # Staff are onboarded by phone number and sign in with the ordinary OTP flow.
    venues = client.get("/api/v1/venues", headers=auth.headers("+212655001122")).json()

    assert venues["total"] == 1
    assert venues["items"][0]["name"] == "Arena Test Casablanca"


# ── Fields ───────────────────────────────────────────────────────────────
def test_create_and_list_fields(client: TestClient, auth, venue_setup) -> None:
    created = client.post(
        f"/api/v1/venues/{venue_setup.venue.id}/fields",
        json={"name": "Pitch 2"},
        headers=auth.headers(MANAGER),
    )

    assert created.status_code == 201
    assert created.json()["camera"] is None

    fields = client.get(
        f"/api/v1/venues/{venue_setup.venue.id}/fields", headers=auth.headers(MANAGER)
    ).json()
    assert [field["name"] for field in fields] == ["Pitch 1", "Pitch 2"]


def test_duplicate_field_name_is_rejected(client: TestClient, auth, venue_setup) -> None:
    response = client.post(
        f"/api/v1/venues/{venue_setup.venue.id}/fields",
        json={"name": "Pitch 1"},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FIELD_NAME_TAKEN"


def test_outsiders_cannot_add_fields(client: TestClient, auth, venue_setup) -> None:
    response = client.post(
        f"/api/v1/venues/{venue_setup.venue.id}/fields",
        json={"name": "Pitch 9"},
        headers=auth.headers(OUTSIDER),
    )

    assert response.status_code == 403


# ── Cameras ──────────────────────────────────────────────────────────────
def test_attaching_a_camera_returns_its_token_once(client: TestClient, auth, venue_setup) -> None:
    field = client.post(
        f"/api/v1/venues/{venue_setup.venue.id}/fields",
        json={"name": "Pitch 2"},
        headers=auth.headers(MANAGER),
    ).json()

    response = client.post(
        f"/api/v1/fields/{field['id']}/camera",
        json={"name": "Pitch 2 — wide 4K", "stream_url": "rtsp://cam2.local/stream"},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token"]
    assert body["camera"]["name"] == "Pitch 2 — wide 4K"
    assert body["camera"]["online"] is False

    # The token is never readable again.
    refetched = client.get(f"/api/v1/fields/{field['id']}", headers=auth.headers(MANAGER)).text
    assert body["token"] not in refetched


def test_reattaching_replaces_the_camera_and_rotates_the_token(
    client: TestClient, auth, venue_setup
) -> None:
    url = f"/api/v1/fields/{venue_setup.field.id}/camera"
    first = client.post(url, json={"name": "Cam A"}, headers=auth.headers(MANAGER)).json()
    second = client.post(url, json={"name": "Cam B"}, headers=auth.headers(MANAGER)).json()

    assert first["token"] != second["token"]
    assert first["camera"]["id"] == second["camera"]["id"]  # one camera per field
    assert second["camera"]["name"] == "Cam B"

    # The old token stops working immediately.
    stale = client.post(
        f"/api/v1/cameras/{second['camera']['id']}/heartbeat",
        json={"status": "ONLINE"},
        headers={"X-Camera-Token": first["token"]},
    )
    assert stale.status_code == 403


def test_detaching_a_camera(client: TestClient, auth, venue_setup) -> None:
    response = client.delete(
        f"/api/v1/fields/{venue_setup.field.id}/camera", headers=auth.headers(MANAGER)
    )

    assert response.status_code == 204
    field = client.get(
        f"/api/v1/fields/{venue_setup.field.id}", headers=auth.headers(MANAGER)
    ).json()
    assert field["camera"] is None
    assert field["camera_id"] is None
