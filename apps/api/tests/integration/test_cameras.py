"""Camera status and the capture agent's heartbeat."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from matchly_shared.domain import Camera, CameraStatus, MatchStatus

MANAGER = "+212600000901"
OUTSIDER = "+212600000902"


def test_status_reports_offline_without_a_heartbeat(client: TestClient, auth, venue_setup) -> None:
    response = client.get(
        f"/api/v1/cameras/{venue_setup.camera.id}/status", headers=auth.headers(MANAGER)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["online"] is False
    assert body["last_seen"] is None
    assert body["current_match_id"] is None


def test_heartbeat_brings_the_camera_online(client: TestClient, auth, venue_setup) -> None:
    beat = client.post(
        f"/api/v1/cameras/{venue_setup.camera.id}/heartbeat",
        json={"status": "ONLINE"},
        headers={"X-Camera-Token": venue_setup.camera_token},
    )

    assert beat.status_code == 200, beat.text
    assert beat.json()["online"] is True

    status = client.get(
        f"/api/v1/cameras/{venue_setup.camera.id}/status", headers=auth.headers(MANAGER)
    ).json()
    assert status["online"] is True
    assert status["status"] == "ONLINE"
    assert status["last_seen"] is not None


def test_online_is_derived_from_last_seen_not_from_status(
    client: TestClient, auth, db: Session, venue_setup
) -> None:
    # An agent that dies without saying goodbye leaves status=ONLINE behind. If
    # the dashboard trusted that column, a venue would discover it had no
    # recording only after the match.
    camera = db.get(Camera, venue_setup.camera.id)
    camera.status = CameraStatus.ONLINE
    camera.last_seen = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    db.commit()

    body = client.get(f"/api/v1/cameras/{camera.id}/status", headers=auth.headers(MANAGER)).json()

    assert body["status"] == "ONLINE"
    assert body["online"] is False


def test_heartbeat_requires_a_token(client: TestClient, venue_setup) -> None:
    response = client.post(
        f"/api/v1/cameras/{venue_setup.camera.id}/heartbeat", json={"status": "ONLINE"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_heartbeat_rejects_a_wrong_token(client: TestClient, venue_setup) -> None:
    response = client.post(
        f"/api/v1/cameras/{venue_setup.camera.id}/heartbeat",
        json={"status": "ONLINE"},
        headers={"X-Camera-Token": "not-the-token"},
    )

    assert response.status_code == 403


def test_a_user_token_does_not_authenticate_a_camera(client: TestClient, auth, venue_setup) -> None:
    # The agent is a machine, not a person; the two credential types must not mix.
    response = client.post(
        f"/api/v1/cameras/{venue_setup.camera.id}/heartbeat",
        json={"status": "ONLINE"},
        headers=auth.headers(MANAGER),
    )

    assert response.status_code == 403


def test_status_is_venue_scoped(client: TestClient, auth, venue_setup) -> None:
    response = client.get(
        f"/api/v1/cameras/{venue_setup.camera.id}/status", headers=auth.headers(OUTSIDER)
    )

    assert response.status_code == 403


def test_status_names_the_match_being_recorded(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(
        field=venue_setup.field, starts_in_hours=-0.5, status=MatchStatus.RECORDING
    )

    body = client.get(
        f"/api/v1/cameras/{venue_setup.camera.id}/status", headers=auth.headers(MANAGER)
    ).json()

    assert body["current_match_id"] == str(match.id)


def test_agent_can_report_an_error_state(client: TestClient, auth, venue_setup) -> None:
    response = client.post(
        f"/api/v1/cameras/{venue_setup.camera.id}/heartbeat",
        json={"status": "ERROR", "note": "RTSP stream dropped"},
        headers={"X-Camera-Token": venue_setup.camera_token},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ERROR"
    # Still "online": the agent is alive and talking, which is what matters for
    # deciding whether anyone will notice the problem.
    assert response.json()["online"] is True
