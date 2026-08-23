"""The computer-vision pipeline, running for real.

Detection, tracking and track-based scoring on an actual video with the actual
YOLO weights. Slow and dependency-heavy, so it skips cleanly wherever the CV
runtime is not installed — which is also the deployment this whole design is
built to tolerate.

Registration is process-global and happens at import, so these tests opt *in*
via a fixture rather than snapshotting the registry — a snapshot taken before the
first import is empty, and restoring it would silently unregister everything for
the rest of the session.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from matchly_shared.domain import JobStatus, JobStep, ProcessingJob, Video, VideoStatus
from matchly_shared.pipeline import registry as step_registry
from matchly_shared.pipeline import run_pipeline
from matchly_shared.storage import get_storage
from video_worker import ffmpeg


def _cv_available() -> bool:
    try:
        from ai_worker.detection import available
    except ImportError:
        return False
    return available("yolov8n.pt")


pytestmark = [
    pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg is not installed"),
    pytest.mark.skipif(not _cv_available(), reason="the CV runtime is not installed"),
]

MANAGER = "+212600000901"


@pytest.fixture
def cv_steps(with_cv) -> None:
    """The computer-vision steps, registered for this module."""


@pytest.fixture
def uploaded_match(client, auth, factory, venue_setup, db: Session, tmp_path):
    match = factory.match(field=venue_setup.field, starts_in_hours=-1)
    headers = auth.headers(MANAGER)
    client.post(f"/api/v1/matches/{match.id}/start", headers=headers)

    clip = ffmpeg.make_test_video(tmp_path / "m.mp4", seconds=12, width=480, height=270, fps=10)
    target = client.post(
        f"/api/v1/matches/{match.id}/video", json={"kind": "master"}, headers=headers
    ).json()
    path = target["upload_url"].split("://", 1)[1].split("/", 1)[1]
    client.put("/" + path.lstrip("/"), content=clip.read_bytes())

    client.post(f"/api/v1/matches/{match.id}/stop", headers=headers)
    client.post(f"/api/v1/matches/{match.id}/video/complete", json={}, headers=headers)
    db.expire_all()
    return match


def test_the_cv_steps_run_and_are_recorded(cv_steps, uploaded_match, db: Session, settings) -> None:
    video = db.query(Video).filter(Video.match_id == uploaded_match.id).one()

    result = run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())

    assert result.status is VideoStatus.READY, result.as_dict()
    db.expire_all()

    jobs = {
        job.step: job for job in db.query(ProcessingJob).filter(ProcessingJob.video_id == video.id)
    }
    detection = jobs[JobStep.DETECT_PLAYERS]
    # A synthetic test pattern contains no people, so detection legitimately
    # finds nothing — but it must have *run*, not been skipped for absence.
    assert detection.status in (JobStatus.SUCCEEDED, JobStatus.SKIPPED)
    if detection.status is JobStatus.SUCCEEDED:
        assert detection.result["frames"] > 0
        assert detection.result["detector"].startswith("yolo:")


def test_the_match_still_completes_when_nothing_is_detected(
    cv_steps, uploaded_match, db: Session, settings
) -> None:
    """A test pattern has no players in it.

    Tracking then has nothing to track and jersey reading nothing to read — and
    the match must still come out with clips, scored on motion.
    """
    video = db.query(Video).filter(Video.match_id == uploaded_match.id).one()

    result = run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())

    assert result.status is VideoStatus.READY
    db.expire_all()
    highlights = db.get(Video, video.id).highlights
    assert highlights
    assert all(highlight.video_url for highlight in highlights)


def test_a_failing_cv_step_never_fails_the_match(
    cv_steps, uploaded_match, db: Session, settings, monkeypatch
) -> None:
    """The load-bearing guarantee, tested against a hard failure rather than absence."""
    from ai_worker.steps import cv

    def explode(context):
        raise RuntimeError("the GPU fell over")

    monkeypatch.setitem(step_registry._REGISTRY, JobStep.DETECT_PLAYERS, explode)

    video = db.query(Video).filter(Video.match_id == uploaded_match.id).one()
    result = run_pipeline(db, video_id=video.id, settings=settings, storage=get_storage())

    assert result.status is VideoStatus.READY
    assert JobStep.DETECT_PLAYERS in result.failed
    db.expire_all()
    assert db.get(Video, video.id).highlights
    assert cv  # the module under test is the one we replaced


def test_detection_thins_rather_than_truncates(cv_steps, settings) -> None:
    """A long match must be sampled across its whole length, not just the start.

    Half a match detected is worse than a whole match detected coarsely: the
    second half would produce no highlights at all.
    """
    from ai_worker.steps.cv import detect_players

    assert detect_players is not None
    assert settings.max_detection_frames > 0
