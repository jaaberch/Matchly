"""The whole journey, with real video and real ffmpeg.

This is the test that says the product works: a recording is uploaded in
segments through the API, the real pipeline joins, probes, transcodes and cuts
it, and the match comes out READY with playable clips.

Skipped when ffmpeg is unavailable — the worker image always has it, a laptop
might not.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from matchly_shared.domain import (
    JobStatus,
    JobStep,
    Match,
    MatchStatus,
    ProcessingJob,
    Video,
    VideoStatus,
)
from matchly_shared.pipeline import run_pipeline
from matchly_shared.storage import get_storage, parse_uri
from video_worker import ffmpeg

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg is not installed")

MANAGER = "+212600000901"
YOUSSEF = "+212600000801"


@pytest.fixture(autouse=True)
def _steps():
    """Register the real ffmpeg steps for this module."""
    import video_worker.steps  # noqa: F401


def _put(client: TestClient, url: str, payload: bytes):
    path = url.split("://", 1)[1].split("/", 1)[1]
    return client.put("/" + path.lstrip("/"), content=payload)


@pytest.fixture
def recorded_match(client: TestClient, auth, factory, venue_setup, db: Session, tmp_path):
    """A match with two real 20-second segments uploaded through the API."""
    match = factory.match(field=venue_setup.field, starts_in_hours=-1)
    headers = auth.headers(MANAGER)
    client.post(f"/api/v1/matches/{match.id}/start", headers=headers)

    agent = {"X-Camera-Token": venue_setup.camera_token}
    for index in range(2):
        clip = ffmpeg.make_test_video(
            tmp_path / f"seg{index}.mp4", seconds=20, width=480, height=270, fps=15
        )
        target = client.post(
            f"/api/v1/matches/{match.id}/video",
            json={"kind": "segment", "segment_index": index},
            headers=agent,
        ).json()
        assert _put(client, target["upload_url"], clip.read_bytes()).status_code == 200
        assert (
            client.post(
                f"/api/v1/matches/{match.id}/video/segments",
                json={"segment_index": index},
                headers=agent,
            ).status_code
            == 201
        )

    client.post(f"/api/v1/matches/{match.id}/stop", headers=headers)
    completed = client.post(
        f"/api/v1/matches/{match.id}/video/complete",
        json={"expected_segments": 2},
        headers=agent,
    )
    assert completed.status_code == 200, completed.text
    db.expire_all()
    return match


def test_a_recording_becomes_a_match_full_of_clips(
    client: TestClient, auth, recorded_match, db: Session, settings
) -> None:
    video = db.query(Video).filter(Video.match_id == recorded_match.id).one()

    result = run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())

    assert result.status is VideoStatus.READY, result.as_dict()
    db.expire_all()
    video = db.get(Video, video.id)
    match = db.get(Match, recorded_match.id)

    # The two segments were joined into one 40-second recording.
    assert match.status is MatchStatus.READY
    assert video.duration == pytest.approx(40, abs=1.5)
    assert (video.width, video.height) == (480, 270)
    assert video.has_audio is True
    assert video.processed_url and video.proxy_url

    highlights = sorted(video.highlights, key=lambda h: h.start_time)
    assert highlights, "the pipeline produced no highlights"
    assert all(h.video_url for h in highlights)
    assert all(h.end_time > h.start_time for h in highlights)
    assert all(h.end_time <= video.duration + 0.5 for h in highlights)
    assert all(0 <= h.score <= 1 for h in highlights)
    assert all(h.signals.get("detector") == "mock-v1" for h in highlights)


def test_the_clips_are_real_playable_video(
    client: TestClient, recorded_match, db: Session, settings
) -> None:
    video = db.query(Video).filter(Video.match_id == recorded_match.id).one()
    run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())
    db.expire_all()

    storage = get_storage()
    highlight = sorted(db.get(Video, video.id).highlights, key=lambda h: h.start_time)[0]

    ref = parse_uri(highlight.video_url)
    info, _ = ffmpeg.probe(storage.local_path(ref.bucket, ref.key))
    assert info.duration == pytest.approx(highlight.end_time - highlight.start_time, abs=0.5)

    vertical_ref = parse_uri(highlight.video_url_vertical)
    vertical, _ = ffmpeg.probe(storage.local_path(vertical_ref.bucket, vertical_ref.key))
    # 9:16 for social, cut from the same moment.
    assert (vertical.width, vertical.height) == (1080, 1920)

    thumb_ref = parse_uri(highlight.thumbnail_url)
    assert storage.stat(thumb_ref.bucket, thumb_ref.key).size > 0


def test_every_implemented_step_is_recorded(recorded_match, db: Session, settings) -> None:
    video = db.query(Video).filter(Video.match_id == recorded_match.id).one()
    run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())
    db.expire_all()

    jobs = {
        job.step: job for job in db.query(ProcessingJob).filter(ProcessingJob.video_id == video.id)
    }
    for step in (
        JobStep.VALIDATE,
        JobStep.PROBE,
        JobStep.TRANSCODE,
        JobStep.SCORE_EVENTS,
        JobStep.CUT_CLIPS,
        JobStep.PERSIST,
    ):
        assert jobs[step].status is JobStatus.SUCCEEDED, f"{step} did not succeed"
        assert jobs[step].attempts == 1

    # The CV steps have no implementation yet; they wait rather than fail, and
    # the match reaches READY without them.
    for step in (JobStep.DETECT_PLAYERS, JobStep.TRACK, JobStep.JERSEY_OCR):
        assert jobs[step].status is JobStatus.PENDING


def test_re_running_does_not_redo_the_expensive_work(recorded_match, db: Session, settings) -> None:
    video = db.query(Video).filter(Video.match_id == recorded_match.id).one()
    run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())

    second = run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())

    # Nothing re-executed: an hour of 4K is never transcoded twice.
    assert second.executed == []
    assert JobStep.TRANSCODE in second.skipped
    assert second.status is VideoStatus.READY


def test_re_running_does_not_duplicate_highlights(recorded_match, db: Session, settings) -> None:
    video = db.query(Video).filter(Video.match_id == recorded_match.id).one()
    run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())
    db.expire_all()
    first_count = len(db.get(Video, video.id).highlights)

    run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage(), force=True)
    db.expire_all()

    assert len(db.get(Video, video.id).highlights) == first_count


def test_highlights_are_delivered_through_the_api(
    client: TestClient, auth, recorded_match, db: Session, settings, factory
) -> None:
    player = factory.user(phone=YOUSSEF, name="Youssef")
    factory.player(match=recorded_match, user=player, jersey_number=7)
    video = db.query(Video).filter(Video.match_id == recorded_match.id).one()
    run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())
    db.expire_all()

    response = client.get(
        f"/api/v1/matches/{recorded_match.id}/highlights", headers=auth.headers(YOUSSEF)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] > 0
    first = body["items"][0]
    # Signed links, not permanent public URLs.
    assert "signature=" in first["video_url"]
    assert first["duration"] == pytest.approx(first["end_time"] - first["start_time"])
    # Ordered as the match played, not by score.
    starts = [item["start_time"] for item in body["items"]]
    assert starts == sorted(starts)
