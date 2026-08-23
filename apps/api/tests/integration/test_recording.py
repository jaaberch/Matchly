"""Match recording: start, stop, upload and enqueue."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from matchly_shared.domain import MatchStatus, Video, VideoStatus
from matchly_shared.storage import keys

MANAGER = "+212600000901"
OUTSIDER = "+212600000902"


@pytest.fixture
def enqueued(monkeypatch) -> list[dict]:
    """Capture what would have been queued, instead of needing a live broker."""
    calls: list[dict] = []

    def fake(video_id, *, force=False):
        calls.append({"video_id": str(video_id), "force": force})
        return "task-123"

    from app.services import job_queue

    monkeypatch.setattr(job_queue, "enqueue_processing", fake)
    return calls


def _upload(client: TestClient, match_id, headers, *, body=None):
    return client.post(
        f"/api/v1/matches/{match_id}/video", json=body or {"kind": "master"}, headers=headers
    )


def _put(client: TestClient, url: str, payload: bytes):
    """Follow a presigned upload URL, as the capture agent would."""
    path = url.split("://", 1)[1].split("/", 1)[1] if "://" in url else url
    return client.put("/" + path.lstrip("/"), content=payload)


# ── Start ────────────────────────────────────────────────────────────────
def test_operator_starts_a_match(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field, starts_in_hours=0.1)

    response = client.post(f"/api/v1/matches/{match.id}/start", headers=auth.headers(MANAGER))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "RECORDING"
    assert body["started_at"] is not None
    assert body["camera"]["online"] is False  # no heartbeat in this fixture


def test_starting_twice_is_not_an_error(client: TestClient, auth, factory, venue_setup) -> None:
    # Venue staff press this on a phone at the side of a pitch. A double tap
    # must never be an error.
    match = factory.match(field=venue_setup.field)
    headers = auth.headers(MANAGER)
    client.post(f"/api/v1/matches/{match.id}/start", headers=headers)

    again = client.post(f"/api/v1/matches/{match.id}/start", headers=headers)

    assert again.status_code == 200
    assert again.json()["status"] == "RECORDING"


def test_a_field_with_no_camera_cannot_record(
    client: TestClient, auth, factory, venue_setup, db: Session
) -> None:
    bare_field = factory.field(venue=venue_setup.venue, name="Pitch 2")
    match = factory.match(field=bare_field)

    response = client.post(f"/api/v1/matches/{match.id}/start", headers=auth.headers(MANAGER))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_CAMERA"


def test_a_finished_match_cannot_be_restarted(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.READY)

    response = client.post(f"/api/v1/matches/{match.id}/start", headers=auth.headers(MANAGER))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MATCH_NOT_STARTABLE"


def test_players_cannot_start_a_match(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field)
    response = client.post(f"/api/v1/matches/{match.id}/start", headers=auth.headers(OUTSIDER))
    assert response.status_code == 403


def test_starting_creates_the_video_row(
    client: TestClient, auth, factory, venue_setup, db: Session
) -> None:
    match = factory.match(field=venue_setup.field)
    client.post(f"/api/v1/matches/{match.id}/start", headers=auth.headers(MANAGER))

    db.expire_all()
    assert db.query(Video).filter(Video.match_id == match.id).count() == 1


# ── Stop ─────────────────────────────────────────────────────────────────
def test_stopping_moves_to_uploading(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    headers = auth.headers(MANAGER)

    response = client.post(f"/api/v1/matches/{match.id}/stop", headers=headers)

    assert response.status_code == 200
    # UPLOADING is resumable, not final: the recording is safe on the pitch even
    # if the network is down.
    assert response.json()["status"] == "UPLOADING"


def test_stopping_twice_is_not_an_error(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    headers = auth.headers(MANAGER)
    client.post(f"/api/v1/matches/{match.id}/stop", headers=headers)

    again = client.post(f"/api/v1/matches/{match.id}/stop", headers=headers)

    assert again.status_code == 200


def test_a_match_that_never_started_cannot_be_stopped(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field)
    response = client.post(f"/api/v1/matches/{match.id}/stop", headers=auth.headers(MANAGER))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MATCH_NOT_RECORDING"


# ── Upload targets ───────────────────────────────────────────────────────
def test_operator_gets_a_presigned_target(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)

    response = _upload(client, match.id, auth.headers(MANAGER))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["method"] == "PUT"
    assert body["bucket"] == "matchly-originals"
    assert body["storage_key"].endswith("master.mp4")
    assert "signature=" in body["upload_url"]


def test_the_capture_agent_can_upload_with_its_camera_token(
    client: TestClient, factory, venue_setup
) -> None:
    # The agent is a machine on the pitch; it has no user session.
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)

    response = client.post(
        f"/api/v1/matches/{match.id}/video",
        json={"kind": "segment", "segment_index": 0},
        headers={"X-Camera-Token": venue_setup.camera_token},
    )

    assert response.status_code == 200, response.text
    assert "segments/00000.mp4" in response.json()["storage_key"]


def test_a_wrong_camera_token_is_refused(client: TestClient, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)

    response = client.post(
        f"/api/v1/matches/{match.id}/video",
        json={"kind": "master"},
        headers={"X-Camera-Token": "not-the-token"},
    )

    assert response.status_code == 403


def test_an_anonymous_caller_cannot_get_an_upload_target(
    client: TestClient, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    assert _upload(client, match.id, {}).status_code == 403


def test_a_scheduled_match_has_nothing_to_upload(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.SCHEDULED)

    response = _upload(client, match.id, auth.headers(MANAGER))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MATCH_NOT_UPLOADABLE"


# ── Upload completion ────────────────────────────────────────────────────
def test_the_whole_upload_round_trip(
    client: TestClient, auth, factory, venue_setup, db: Session
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    headers = auth.headers(MANAGER)

    target = _upload(client, match.id, headers).json()
    assert _put(client, target["upload_url"], b"x" * 5000).status_code == 200

    completed = client.post(f"/api/v1/matches/{match.id}/video/complete", json={}, headers=headers)

    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["status"] == "UPLOADED"
    assert body["size_bytes"] == 5000
    # Retention is stamped from the venue's policy at completion time.
    assert body["purge_after"] is not None


def test_completing_without_uploading_anything_is_refused(
    client: TestClient, auth, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    headers = auth.headers(MANAGER)
    _upload(client, match.id, headers)

    response = client.post(f"/api/v1/matches/{match.id}/video/complete", json={}, headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RECORDING_MISSING"


def test_a_truncated_upload_is_rejected(client: TestClient, auth, factory, venue_setup) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    headers = auth.headers(MANAGER)
    target = _upload(client, match.id, headers).json()
    _put(client, target["upload_url"], b"tiny")

    response = client.post(f"/api/v1/matches/{match.id}/video/complete", json={}, headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RECORDING_TOO_SMALL"


# ── Segments ─────────────────────────────────────────────────────────────
def test_segments_are_tracked_and_completion_waits_for_all_of_them(
    client: TestClient, factory, venue_setup, db: Session
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    agent = {"X-Camera-Token": venue_setup.camera_token}

    for index in (0, 1):
        target = client.post(
            f"/api/v1/matches/{match.id}/video",
            json={"kind": "segment", "segment_index": index},
            headers=agent,
        ).json()
        _put(client, target["upload_url"], b"y" * 4000)
        recorded = client.post(
            f"/api/v1/matches/{match.id}/video/segments",
            json={"segment_index": index, "duration": 600.0},
            headers=agent,
        )
        assert recorded.status_code == 201, recorded.text

    # Three were recorded on the pitch but only two arrived: not complete.
    incomplete = client.post(
        f"/api/v1/matches/{match.id}/video/complete",
        json={"expected_segments": 3},
        headers=agent,
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == "SEGMENTS_INCOMPLETE"
    assert incomplete.json()["error"]["details"]["missing"] == [2]

    done = client.post(
        f"/api/v1/matches/{match.id}/video/complete",
        json={"expected_segments": 2},
        headers=agent,
    )
    assert done.status_code == 200
    assert done.json()["status"] == "UPLOADED"
    assert len(done.json()["segments"]) == 2


def test_a_segment_cannot_be_confirmed_before_it_arrives(
    client: TestClient, factory, venue_setup
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)

    response = client.post(
        f"/api/v1/matches/{match.id}/video/segments",
        json={"segment_index": 0},
        headers={"X-Camera-Token": venue_setup.camera_token},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SEGMENT_MISSING"


def test_re_confirming_a_segment_does_not_duplicate_it(
    client: TestClient, factory, venue_setup
) -> None:
    # Agents retry. The same segment arriving twice must not become two rows.
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    agent = {"X-Camera-Token": venue_setup.camera_token}
    target = client.post(
        f"/api/v1/matches/{match.id}/video",
        json={"kind": "segment", "segment_index": 0},
        headers=agent,
    ).json()
    _put(client, target["upload_url"], b"z" * 3000)

    for _ in range(3):
        client.post(
            f"/api/v1/matches/{match.id}/video/segments",
            json={"segment_index": 0},
            headers=agent,
        )

    done = client.post(
        f"/api/v1/matches/{match.id}/video/complete",
        json={"expected_segments": 1},
        headers=agent,
    ).json()
    assert len(done["segments"]) == 1


# ── Processing ───────────────────────────────────────────────────────────
def test_processing_is_queued_not_run_inline(
    client: TestClient, auth, factory, venue_setup, enqueued
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    headers = auth.headers(MANAGER)
    target = _upload(client, match.id, headers).json()
    _put(client, target["upload_url"], b"x" * 5000)
    client.post(f"/api/v1/matches/{match.id}/video/complete", json={}, headers=headers)

    response = client.post(f"/api/v1/matches/{match.id}/process", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PROCESSING"
    assert response.json()["task_id"] == "task-123"
    assert enqueued == [{"video_id": response.json()["video_id"], "force": False}]


def test_force_is_passed_through(client: TestClient, auth, factory, venue_setup, enqueued) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    headers = auth.headers(MANAGER)
    target = _upload(client, match.id, headers).json()
    _put(client, target["upload_url"], b"x" * 5000)
    client.post(f"/api/v1/matches/{match.id}/video/complete", json={}, headers=headers)

    client.post(f"/api/v1/matches/{match.id}/process?force=true", headers=headers)

    assert enqueued[0]["force"] is True


def test_processing_an_unfinished_upload_is_refused(
    client: TestClient, auth, factory, venue_setup, enqueued
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    headers = auth.headers(MANAGER)
    _upload(client, match.id, headers)  # creates the video row, uploads nothing

    response = client.post(f"/api/v1/matches/{match.id}/process", headers=headers)

    assert response.status_code == 409
    # The upload was never marked complete, so there is nothing to work on and
    # nothing is queued.
    assert response.json()["error"]["code"] == "VIDEO_NOT_UPLOADED"
    assert enqueued == []


def test_a_broker_outage_is_a_clear_503(
    client: TestClient, auth, factory, venue_setup, monkeypatch
) -> None:
    """The recording is safe; only the processing is delayed. Say so."""
    from app.services import job_queue

    def explode(*args, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(job_queue.get_celery_app(), "send_task", explode)

    match = factory.match(field=venue_setup.field, status=MatchStatus.RECORDING)
    headers = auth.headers(MANAGER)
    target = _upload(client, match.id, headers).json()
    _put(client, target["upload_url"], b"x" * 5000)
    client.post(f"/api/v1/matches/{match.id}/video/complete", json={}, headers=headers)

    response = client.post(f"/api/v1/matches/{match.id}/process", headers=headers)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "QUEUE_UNAVAILABLE"
    assert "safe" in response.json()["error"]["message"]


# ── Status ───────────────────────────────────────────────────────────────
def test_players_can_watch_processing_progress(
    client: TestClient, auth, factory, venue_setup, db: Session
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.PROCESSING)
    player = factory.user(phone="+212600000801", name="Youssef")
    factory.player(match=match, user=player)
    db.add(Video(match_id=match.id, status=VideoStatus.PROCESSING, duration=3600.0))
    db.commit()

    response = client.get(
        f"/api/v1/matches/{match.id}/video", headers=auth.headers("+212600000801")
    )

    assert response.status_code == 200
    assert response.json()["status"] == "PROCESSING"
    assert response.json()["duration"] == 3600.0


def test_outsiders_cannot_see_a_recording(
    client: TestClient, auth, factory, venue_setup, db: Session
) -> None:
    match = factory.match(field=venue_setup.field, status=MatchStatus.PROCESSING)
    db.add(Video(match_id=match.id, status=VideoStatus.PROCESSING))
    db.commit()

    response = client.get(f"/api/v1/matches/{match.id}/video", headers=auth.headers(OUTSIDER))

    assert response.status_code == 403


def test_deterministic_object_keys() -> None:
    # Retried steps must overwrite their own output, never duplicate it.
    assert keys.master_key("m1", "v1") == keys.master_key("m1", "v1")
    assert keys.segment_key("m1", "v1", 3).endswith("segments/00003.mp4")
