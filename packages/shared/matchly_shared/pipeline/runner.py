"""The pipeline runner: job state, idempotency, retries and fallbacks.

One `processing_jobs` row per (video, step), enforced by a unique constraint. The
runner is the only thing that writes those rows, so the rules live in one place:

* A step that already SUCCEEDED with the same fingerprint is skipped.
* A step whose inputs changed re-runs even though it previously succeeded.
* A step that raises is recorded with its error. If it is in ``REQUIRED_STEPS``
  the pipeline stops and the match fails; otherwise the pipeline carries on.
  That is the mechanism behind "every AI component has a fallback" — the match
  still reaches READY with a full replay when detection or OCR is unavailable.
* A step this process cannot run (not registered here) is left PENDING rather
  than failed, so another worker — or a later phase — can pick it up.

Nothing here imports Celery. The worker wraps it; tests call it directly.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import tempfile
import traceback
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..domain import (
    PIPELINE_ORDER,
    REQUIRED_STEPS,
    JobStatus,
    JobStep,
    Match,
    MatchStatus,
    ProcessingJob,
    Video,
    VideoStatus,
)
from ..logging import bind_log_context, get_logger, reset_log_context
from ..storage import ObjectStorage, get_storage
from ..timeutil import utcnow
from .registry import StepContext, StepSkipped, get_step

logger = get_logger(__name__)

#: A job left RUNNING longer than this is assumed to belong to a dead worker.
STUCK_JOB_TIMEOUT = dt.timedelta(minutes=90)


@dataclasses.dataclass(slots=True)
class PipelineResult:
    video_id: uuid.UUID
    executed: list[JobStep]
    skipped: list[JobStep]
    failed: list[JobStep]
    pending: list[JobStep]
    status: VideoStatus

    @property
    def ok(self) -> bool:
        return self.status is not VideoStatus.FAILED

    def as_dict(self) -> dict:
        return {
            "video_id": str(self.video_id),
            "executed": [step.value for step in self.executed],
            "skipped": [step.value for step in self.skipped],
            "failed": [step.value for step in self.failed],
            "pending": [step.value for step in self.pending],
            "status": self.status.value,
        }


def get_or_create_job(session: Session, *, video_id: uuid.UUID, step: JobStep) -> ProcessingJob:
    """Fetch this video's row for a step, creating it once.

    Two workers can reach this at the same moment, so a lost insert race is
    resolved by re-reading rather than by failing.
    """
    job = session.scalars(
        select(ProcessingJob).where(ProcessingJob.video_id == video_id, ProcessingJob.step == step)
    ).first()
    if job is not None:
        return job

    job = ProcessingJob(video_id=video_id, step=step, status=JobStatus.PENDING)
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        job = session.scalars(
            select(ProcessingJob).where(
                ProcessingJob.video_id == video_id, ProcessingJob.step == step
            )
        ).one()
    return job


def _mark_running(session: Session, job: ProcessingJob, *, fingerprint: str | None) -> None:
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.started_at = utcnow()
    job.finished_at = None
    job.last_error = None
    if fingerprint is not None:
        job.fingerprint = fingerprint
    session.commit()  # visible to the admin dashboard while the step runs


def _mark_succeeded(session: Session, job: ProcessingJob, result: dict) -> None:
    job.status = JobStatus.SUCCEEDED
    job.result = result or {}
    job.last_error = None
    job.finished_at = utcnow()
    session.commit()


def _mark_skipped(session: Session, job: ProcessingJob, reason: str) -> None:
    job.status = JobStatus.SKIPPED
    job.result = {"reason": reason}
    job.finished_at = utcnow()
    session.commit()


def _mark_failed(session: Session, job: ProcessingJob, error: BaseException) -> None:
    job.status = JobStatus.FAILED
    job.last_error = f"{type(error).__name__}: {error}"[:4000]
    job.finished_at = utcnow()
    session.commit()


def _should_skip(job: ProcessingJob, *, fingerprint: str, force: bool) -> bool:
    if force:
        return False
    return job.status is JobStatus.SUCCEEDED and job.fingerprint == fingerprint


def _step_fingerprint(video: Video, step: JobStep, settings: Settings) -> str:
    """Identity of what was *uploaded*, so a completed step can be skipped.

    Deliberately excludes anything a step produces. VALIDATE joins segments and
    writes ``original_url`` and ``size_bytes``; if those fed the fingerprint,
    every run would see "the inputs changed" and re-join an hour of 4K forever.

    So the identity is the upload manifest: the segments as they arrived, or —
    when a single master was uploaded — that object. Both are fixed once the
    upload completes and only change if the match is genuinely re-uploaded.
    """
    from .fingerprint import fingerprint as make_fingerprint

    segments = sorted((segment.segment_index, segment.size_bytes) for segment in video.segments)
    return make_fingerprint(
        step.value,
        str(video.id),
        segments or None,
        # Only an input when there are no segments to join.
        None if segments else video.original_url,
        settings.storage_bucket_originals,
        settings.storage_bucket_derived,
    )


def run_pipeline(
    session: Session,
    *,
    video_id: uuid.UUID,
    settings: Settings | None = None,
    storage: ObjectStorage | None = None,
    force: bool = False,
    only: JobStep | None = None,
) -> PipelineResult:
    """Walk the pipeline for one video.

    ``force`` re-runs steps that already succeeded. ``only`` runs a single step,
    which is what the admin "retry this job" action uses.
    """
    settings = settings or get_settings()
    storage = storage or get_storage()

    video = session.get(Video, video_id)
    if video is None:
        raise LookupError(f"No video {video_id}")
    match = session.get(Match, video.match_id)

    steps = [only] if only is not None else list(PIPELINE_ORDER)

    executed: list[JobStep] = []
    skipped: list[JobStep] = []
    failed: list[JobStep] = []
    pending: list[JobStep] = []

    token = bind_log_context(video_id=str(video_id), match_id=str(video.match_id))
    if only is None:
        video.status = VideoStatus.PROCESSING
        if match is not None and match.status is not MatchStatus.PROCESSING:
            match.status = MatchStatus.PROCESSING
        session.commit()

    with tempfile.TemporaryDirectory(prefix=f"matchly-{video_id}-") as tmp:
        workdir = Path(tmp)
        try:
            for step in steps:
                function = get_step(step)
                job = get_or_create_job(session, video_id=video_id, step=step)

                if function is None:
                    # Not implemented in this process. Leave it PENDING so a
                    # worker that does have it — or a later phase — can run it.
                    pending.append(step)
                    if step in REQUIRED_STEPS:
                        logger.info(
                            "pipeline.step_unavailable",
                            extra={"step": step.value, "required": True},
                        )
                    continue

                mark = _step_fingerprint(video, step, settings)
                if _should_skip(job, fingerprint=mark, force=force):
                    skipped.append(step)
                    logger.info("pipeline.step_cached", extra={"step": step.value})
                    continue

                context = StepContext(
                    session=session,
                    video=video,
                    match=match,
                    job=job,
                    storage=storage,
                    settings=settings,
                    workdir=workdir,
                    force=force,
                )

                _mark_running(session, job, fingerprint=mark)
                logger.info("pipeline.step_started", extra={"step": step.value})
                try:
                    result = function(context) or {}
                except StepSkipped as exc:
                    session.rollback()
                    _mark_skipped(session, job, str(exc) or "nothing to do")
                    skipped.append(step)
                    logger.info("pipeline.step_skipped", extra={"step": step.value})
                    continue
                except Exception as exc:  # noqa: BLE001 - recorded, then triaged below
                    session.rollback()
                    _mark_failed(session, job, exc)
                    failed.append(step)
                    logger.error(
                        "pipeline.step_failed",
                        extra={
                            "step": step.value,
                            "required": step in REQUIRED_STEPS,
                            "attempts": job.attempts,
                            "traceback": traceback.format_exc(limit=6),
                        },
                    )
                    if step in REQUIRED_STEPS:
                        _fail_video(session, video, match, step, exc)
                        return PipelineResult(
                            video_id=video_id,
                            executed=executed,
                            skipped=skipped,
                            failed=failed,
                            pending=pending,
                            status=VideoStatus.FAILED,
                        )
                    # Optional step: the match still gets a replay and
                    # motion-based highlights.
                    continue

                _mark_succeeded(session, job, result)
                executed.append(step)
                logger.info("pipeline.step_finished", extra={"step": step.value})
        finally:
            reset_log_context(token)

    status = _settle(session, video, match, pending=pending, only=only)
    return PipelineResult(
        video_id=video_id,
        executed=executed,
        skipped=skipped,
        failed=failed,
        pending=pending,
        status=status,
    )


def _fail_video(
    session: Session, video: Video, match: Match | None, step: JobStep, error: BaseException
) -> None:
    reason = f"{step.value} failed: {type(error).__name__}: {error}"[:1000]
    video.status = VideoStatus.FAILED
    video.failure_reason = reason
    if match is not None:
        match.status = MatchStatus.FAILED
        match.failure_reason = reason
    session.commit()


def _settle(
    session: Session,
    video: Video,
    match: Match | None,
    *,
    pending: list[JobStep],
    only: JobStep | None,
) -> VideoStatus:
    """Decide the final state once the walk finishes."""
    if only is not None:
        session.commit()
        return video.status

    # The match is only READY when every required step has actually run.
    required_outstanding = [step for step in pending if step in REQUIRED_STEPS]
    if required_outstanding:
        video.status = VideoStatus.PROCESSING
        logger.info(
            "pipeline.incomplete",
            extra={"outstanding": [step.value for step in required_outstanding]},
        )
    else:
        video.status = VideoStatus.READY
        if match is not None:
            match.status = MatchStatus.READY
    session.commit()
    return video.status


# ── Maintenance ──────────────────────────────────────────────────────────
def reap_stuck_jobs(session: Session, *, timeout: dt.timedelta = STUCK_JOB_TIMEOUT) -> int:
    """Return jobs abandoned by a dead worker to PENDING.

    ``task_acks_late`` re-delivers the Celery message, but the row would stay
    RUNNING forever and the admin dashboard would lie about it.
    """
    cutoff = utcnow() - timeout
    stuck = session.scalars(
        select(ProcessingJob).where(
            ProcessingJob.status == JobStatus.RUNNING, ProcessingJob.started_at < cutoff
        )
    ).all()
    for job in stuck:
        job.status = JobStatus.PENDING
        job.last_error = "Reset by the reaper: the worker running this step disappeared."
        job.finished_at = None
        logger.warning(
            "pipeline.job_reaped",
            extra={"job_id": str(job.id), "step": job.step.value, "attempts": job.attempts},
        )
    session.commit()
    return len(stuck)
