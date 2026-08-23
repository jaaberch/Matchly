"""The promise: the AI is an enhancement, never a dependency.

Every test here removes some part of the computer-vision stack and asserts the
match still reaches READY with watchable clips. If any of these start failing,
a venue somewhere gets no highlights because a model file moved.
"""

from __future__ import annotations

import pytest
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
from matchly_shared.storage import get_storage
from video_worker import ffmpeg

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg is not installed")

MANAGER = "+212600000901"


@pytest.fixture(autouse=True)
def _no_cv(without_cv):
    """Every test in this module runs as a worker with no computer vision."""


@pytest.fixture
def uploaded_match(client, auth, factory, venue_setup, db: Session, tmp_path):
    """A short real recording, uploaded and ready to process."""
    match = factory.match(field=venue_setup.field, starts_in_hours=-1)
    headers = auth.headers(MANAGER)
    client.post(f"/api/v1/matches/{match.id}/start", headers=headers)

    clip = ffmpeg.make_test_video(tmp_path / "match.mp4", seconds=30, width=480, height=270, fps=15)
    target = client.post(
        f"/api/v1/matches/{match.id}/video", json={"kind": "master"}, headers=headers
    ).json()
    path = target["upload_url"].split("://", 1)[1].split("/", 1)[1]
    assert client.put("/" + path.lstrip("/"), content=clip.read_bytes()).status_code == 200

    client.post(f"/api/v1/matches/{match.id}/stop", headers=headers)
    assert (
        client.post(
            f"/api/v1/matches/{match.id}/video/complete", json={}, headers=headers
        ).status_code
        == 200
    )
    db.expire_all()
    return match


def _jobs(db: Session, video_id) -> dict[JobStep, ProcessingJob]:
    return {
        job.step: job for job in db.query(ProcessingJob).filter(ProcessingJob.video_id == video_id)
    }


def test_a_match_completes_with_no_computer_vision_at_all(
    uploaded_match, db: Session, settings
) -> None:
    video = db.query(Video).filter(Video.match_id == uploaded_match.id).one()

    result = run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())

    assert result.status is VideoStatus.READY, result.as_dict()
    db.expire_all()
    assert db.get(Match, uploaded_match.id).status is MatchStatus.READY

    highlights = db.get(Video, video.id).highlights
    assert highlights, "a match with no CV still owes the players clips"
    assert all(h.video_url for h in highlights)


def test_the_cv_steps_wait_rather_than_fail(uploaded_match, db: Session, settings) -> None:
    video = db.query(Video).filter(Video.match_id == uploaded_match.id).one()
    run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())
    db.expire_all()

    jobs = _jobs(db, video.id)
    for step in (JobStep.DETECT_PLAYERS, JobStep.TRACK, JobStep.JERSEY_OCR):
        # PENDING, not FAILED: nothing went wrong, the work simply has no owner
        # in this deployment. A worker with the CV runtime can still pick it up.
        assert jobs[step].status is JobStatus.PENDING
        assert jobs[step].attempts == 0
        assert jobs[step].last_error is None


def test_highlights_are_unattributed_without_jersey_recognition(
    uploaded_match, db: Session, settings, factory
) -> None:
    player = factory.user(phone="+212600000801", name="Youssef")
    factory.player(match=uploaded_match, user=player, jersey_number=7)
    video = db.query(Video).filter(Video.match_id == uploaded_match.id).one()

    run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())
    db.expire_all()

    highlights = db.get(Video, video.id).highlights
    # No attribution is the documented outcome, and the clips are still delivered
    # as general match highlights.
    assert all(highlight.player_id is None for highlight in highlights)
    assert all(highlight.video_url for highlight in highlights)


def test_the_detector_used_is_recorded_on_every_clip(uploaded_match, db: Session, settings) -> None:
    video = db.query(Video).filter(Video.match_id == uploaded_match.id).one()
    run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())
    db.expire_all()

    detectors = {h.signals.get("detector") for h in db.get(Video, video.id).highlights}
    # Which detector produced a match's clips has to be traceable, because it is
    # the first question when the highlights look wrong.
    assert detectors <= {"motion-v1", "mock-v1"}
    assert None not in detectors


def test_it_scores_on_pixels_rather_than_guessing(uploaded_match, db: Session, settings) -> None:
    video = db.query(Video).filter(Video.match_id == uploaded_match.id).one()
    run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())
    db.expire_all()

    job = _jobs(db, video.id)[JobStep.SCORE_EVENTS]
    assert job.status is JobStatus.SUCCEEDED
    # The motion detector watched the recording; the mock is the floor beneath it.
    assert job.result["detector"] == "motion-v1"


def test_no_tracks_are_persisted_without_tracking(uploaded_match, db: Session, settings) -> None:
    video = db.query(Video).filter(Video.match_id == uploaded_match.id).one()
    run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())
    db.expire_all()

    assert db.get(Video, video.id).tracks == []
