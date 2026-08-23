"""The job state machine: idempotency, fallbacks and the reaper.

These use throwaway steps rather than the real ffmpeg ones, so they test the
orchestration rules on their own — which is where the subtle behaviour lives.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy import select
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
from matchly_shared.pipeline import (
    StepError,
    StepSkipped,
    get_or_create_job,
    reap_stuck_jobs,
    registry,
    run_pipeline,
)
from matchly_shared.storage import LocalStorage
from matchly_shared.timeutil import utcnow


@pytest.fixture
def clean_registry() -> Iterator[dict]:
    """Swap the step registry out, so real ffmpeg steps do not run here."""
    saved = dict(registry._REGISTRY)
    registry._REGISTRY.clear()
    yield registry._REGISTRY
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)


@pytest.fixture
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path, signing_key="pipeline-test")


@pytest.fixture
def video(db: Session, factory, venue_setup) -> Video:
    match = factory.match(field=venue_setup.field, status=MatchStatus.UPLOADING)
    video = Video(
        match_id=match.id,
        status=VideoStatus.UPLOADED,
        original_url="file://matchly-originals/master.mp4",
        size_bytes=1_000_000,
        duration=3600.0,
    )
    db.add(video)
    db.commit()
    return video


def _register_all(registry_dict, function) -> None:
    """Give every pipeline step the same behaviour."""
    for step in JobStep:
        registry_dict[step] = function


# ── Job rows ─────────────────────────────────────────────────────────────
def test_a_job_row_is_created_once_per_step(db: Session, video: Video) -> None:
    first = get_or_create_job(db, video_id=video.id, step=JobStep.PROBE)
    second = get_or_create_job(db, video_id=video.id, step=JobStep.PROBE)

    assert first.id == second.id
    assert first.status is JobStatus.PENDING


# ── Happy path ───────────────────────────────────────────────────────────
def test_every_step_runs_and_the_match_becomes_ready(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    _register_all(clean_registry, lambda context: {"ok": True})

    result = run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    assert result.status is VideoStatus.READY
    assert len(result.executed) == len(JobStep)
    assert db.get(Match, video.match_id).status is MatchStatus.READY


def test_results_are_recorded_on_the_job(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    _register_all(clean_registry, lambda context: {"frames": 7200})

    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    job = db.scalars(select(ProcessingJob).where(ProcessingJob.step == JobStep.SAMPLE_FRAMES)).one()
    assert job.status is JobStatus.SUCCEEDED
    assert job.result == {"frames": 7200}
    assert job.attempts == 1
    assert job.finished_at is not None


# ── Idempotency ──────────────────────────────────────────────────────────
def test_a_second_run_reuses_completed_steps(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    calls: list[str] = []
    _register_all(clean_registry, lambda context: calls.append(context.job.step.value) or {})

    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)
    first_pass = len(calls)
    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    # An hour of 4K must never be re-transcoded because a later step was retried.
    assert len(calls) == first_pass
    assert first_pass == len(JobStep)


def test_force_reruns_everything(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    calls: list[str] = []
    _register_all(clean_registry, lambda context: calls.append(context.job.step.value) or {})

    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)
    run_pipeline(db, video_id=video.id, settings=settings, storage=storage, force=True)

    assert len(calls) == len(JobStep) * 2
    job = db.scalars(select(ProcessingJob).where(ProcessingJob.step == JobStep.PROBE)).one()
    assert job.attempts == 2


def test_a_changed_recording_invalidates_completed_steps(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    calls: list[str] = []
    _register_all(clean_registry, lambda context: calls.append(context.job.step.value) or {})

    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)
    # The venue re-uploaded the match: same video row, different bytes.
    video.original_url = "file://matchly-originals/master-v2.mp4"
    video.size_bytes = 2_000_000
    db.commit()
    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    assert len(calls) == len(JobStep) * 2


def test_only_runs_a_single_step(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    calls: list[str] = []
    _register_all(clean_registry, lambda context: calls.append(context.job.step.value) or {})

    run_pipeline(db, video_id=video.id, settings=settings, storage=storage, only=JobStep.PROBE)

    assert calls == [JobStep.PROBE.value]


# ── Failure handling ─────────────────────────────────────────────────────
def test_a_required_step_failing_fails_the_match(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    def step(context):
        if context.job.step is JobStep.TRANSCODE:
            raise StepError("the encoder died")
        return {}

    _register_all(clean_registry, step)

    result = run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    assert result.status is VideoStatus.FAILED
    assert JobStep.TRANSCODE in result.failed
    match = db.get(Match, video.match_id)
    assert match.status is MatchStatus.FAILED
    assert "the encoder died" in match.failure_reason
    # The pipeline stops: no point cutting clips from a replay that does not exist.
    assert JobStep.CUT_CLIPS not in result.executed


def test_an_optional_step_failing_still_delivers_the_match(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    """The fallback promise: AI is an enhancement, never a dependency."""

    def step(context):
        if context.job.step in (JobStep.DETECT_PLAYERS, JobStep.TRACK, JobStep.JERSEY_OCR):
            raise StepError("no GPU available")
        return {}

    _register_all(clean_registry, step)

    result = run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    assert result.status is VideoStatus.READY
    assert db.get(Match, video.match_id).status is MatchStatus.READY
    assert JobStep.DETECT_PLAYERS in result.failed
    assert JobStep.CUT_CLIPS in result.executed


def test_the_error_is_kept_on_the_job(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    def step(context):
        if context.job.step is JobStep.JERSEY_OCR:
            raise StepError("model file missing")
        return {}

    _register_all(clean_registry, step)
    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    job = db.scalars(select(ProcessingJob).where(ProcessingJob.step == JobStep.JERSEY_OCR)).one()
    assert job.status is JobStatus.FAILED
    assert "model file missing" in job.last_error


def test_a_skipped_step_is_not_a_failure(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    def step(context):
        if context.job.step is JobStep.THUMBNAILS:
            raise StepSkipped("nothing to do")
        return {}

    _register_all(clean_registry, step)
    result = run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    assert result.status is VideoStatus.READY
    job = db.scalars(select(ProcessingJob).where(ProcessingJob.step == JobStep.THUMBNAILS)).one()
    assert job.status is JobStatus.SKIPPED


def test_a_retry_resumes_at_the_failed_step(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    calls: list[str] = []
    fail_transcode = {"value": True}

    def step(context):
        calls.append(context.job.step.value)
        if context.job.step is JobStep.TRANSCODE and fail_transcode["value"]:
            raise StepError("transient encoder error")
        return {}

    _register_all(clean_registry, step)
    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)
    calls.clear()

    fail_transcode["value"] = False
    result = run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    # VALIDATE and PROBE already succeeded, so the retry starts at TRANSCODE.
    assert JobStep.VALIDATE.value not in calls
    assert calls[0] == JobStep.TRANSCODE.value
    assert result.status is VideoStatus.READY


# ── Steps this worker cannot run ─────────────────────────────────────────
def test_unregistered_steps_stay_pending(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    # This is how the CV steps behave before the AI worker exists: left for
    # someone else to run, not marked failed.
    for step in (
        JobStep.VALIDATE,
        JobStep.PROBE,
        JobStep.TRANSCODE,
        JobStep.SCORE_EVENTS,
        JobStep.CUT_CLIPS,
        JobStep.PERSIST,
    ):
        clean_registry[step] = lambda context: {}

    result = run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    assert JobStep.DETECT_PLAYERS in result.pending
    assert result.status is VideoStatus.READY
    job = db.scalars(
        select(ProcessingJob).where(ProcessingJob.step == JobStep.DETECT_PLAYERS)
    ).one()
    assert job.status is JobStatus.PENDING


def test_a_missing_required_step_leaves_the_match_processing(
    db: Session, video: Video, storage, clean_registry, settings
) -> None:
    clean_registry[JobStep.VALIDATE] = lambda context: {}

    result = run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    # Not READY and not FAILED: the work simply has not happened yet.
    assert result.status is VideoStatus.PROCESSING
    assert db.get(Match, video.match_id).status is MatchStatus.PROCESSING


# ── Reaper ───────────────────────────────────────────────────────────────
def test_the_reaper_returns_abandoned_jobs_to_the_queue(db: Session, video: Video) -> None:
    job = get_or_create_job(db, video_id=video.id, step=JobStep.TRANSCODE)
    job.status = JobStatus.RUNNING
    job.attempts = 1
    job.started_at = utcnow() - dt.timedelta(hours=3)
    db.commit()

    assert reap_stuck_jobs(db) == 1

    db.refresh(job)
    assert job.status is JobStatus.PENDING
    assert "worker" in job.last_error


def test_the_reaper_leaves_healthy_jobs_alone(db: Session, video: Video) -> None:
    job = get_or_create_job(db, video_id=video.id, step=JobStep.TRANSCODE)
    job.status = JobStatus.RUNNING
    job.started_at = utcnow() - dt.timedelta(minutes=2)
    db.commit()

    assert reap_stuck_jobs(db) == 0
    db.refresh(job)
    assert job.status is JobStatus.RUNNING


# ── Fingerprints ─────────────────────────────────────────────────────────
def test_a_step_that_writes_its_own_input_still_caches(
    db: Session, factory, venue_setup, storage, clean_registry, settings
) -> None:
    """VALIDATE joins segments and sets ``original_url``.

    If that output fed the fingerprint, every run would see changed inputs and
    re-join the recording forever. The fingerprint covers the upload manifest
    instead, so a completed join stays completed.
    """
    from matchly_shared.domain import VideoSegment

    match = factory.match(field=venue_setup.field, status=MatchStatus.UPLOADING)
    video = Video(match_id=match.id, status=VideoStatus.UPLOADED, duration=60.0)
    db.add(video)
    db.flush()
    db.add(
        VideoSegment(
            video_id=video.id, segment_index=0, storage_url="file://b/seg0.mp4", size_bytes=1000
        )
    )
    db.commit()

    calls: list[str] = []

    def joining_step(context):
        calls.append(context.job.step.value)
        # Exactly what VALIDATE does with segments.
        context.video.original_url = "file://matchly-originals/joined.mp4"
        context.video.size_bytes = 999_999
        return {}

    _register_all(clean_registry, joining_step)

    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)
    first_pass = len(calls)
    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    assert len(calls) == first_pass


def test_a_re_uploaded_recording_does_invalidate(
    db: Session, factory, venue_setup, storage, clean_registry, settings
) -> None:
    from matchly_shared.domain import VideoSegment

    match = factory.match(field=venue_setup.field, status=MatchStatus.UPLOADING)
    video = Video(match_id=match.id, status=VideoStatus.UPLOADED, duration=60.0)
    db.add(video)
    db.flush()
    segment = VideoSegment(
        video_id=video.id, segment_index=0, storage_url="file://b/seg0.mp4", size_bytes=1000
    )
    db.add(segment)
    db.commit()

    calls: list[str] = []
    _register_all(clean_registry, lambda context: calls.append(context.job.step.value) or {})

    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)
    first_pass = len(calls)

    # The venue re-recorded the match: a different segment arrived.
    segment.size_bytes = 5000
    db.commit()
    run_pipeline(db, video_id=video.id, settings=settings, storage=storage)

    assert len(calls) == first_pass * 2
