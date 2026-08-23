"""SCORE_EVENTS, CUT_CLIPS, THUMBNAILS and PERSIST — candidates to shareable clips."""

from __future__ import annotations

import uuid

from matchly_shared.domain import Highlight, JobStep, MatchStatus, VideoStatus
from matchly_shared.logging import get_logger
from matchly_shared.pipeline import StepContext, StepError, StepSkipped, register_step
from matchly_shared.storage import keys
from matchly_shared.timeutil import utcnow

from .. import ffmpeg
from ..highlights import DetectionRequest, build_detector, select
from ._source import proxy_source, readable

logger = get_logger(__name__)


@register_step(JobStep.SCORE_EVENTS)
def score_events(context: StepContext) -> dict:
    """Find the moments worth watching and write them as highlight rows.

    Rows are created here, before any clip exists, so each one has an id — and
    therefore a deterministic object key — before CUT_CLIPS runs. That is what
    makes clip cutting idempotent: a retry overwrites its own file instead of
    leaving orphans behind.

    Re-running replaces the previous selection wholesale rather than adding to
    it, so a forced re-run cannot double a match's highlights.
    """
    video = context.video
    if not video.duration:
        raise StepError("cannot score events before the recording has been probed")

    frames_dir = context.workdir / "frames"
    frames = sorted(frames_dir.glob("*.jpg")) if frames_dir.is_dir() else []

    proxy_path = None
    if video.proxy_url:
        candidate_source = proxy_source(context)
        proxy_path = candidate_source if hasattr(candidate_source, "is_file") else None

    detector = build_detector("mock")
    candidates = detector.detect(
        DetectionRequest(
            video_id=str(video.id),
            duration=video.duration,
            proxy_path=proxy_path,
            frames=frames,
            frame_fps=context.settings.frame_sample_fps,
            has_audio=video.has_audio,
        )
    )

    windows = select(candidates, duration=video.duration, settings=context.settings)
    if not windows:
        raise StepSkipped("no candidate moments cleared the score threshold")

    # Clear the previous selection, including its stored clips.
    for existing in list(video.highlights):
        context.session.delete(existing)
    context.session.flush()
    # Deleting rows does not empty an already-loaded collection; expire it so the
    # later steps see the new selection rather than the old one.
    context.session.expire(video, ["highlights"])
    context.storage.delete_prefix(context.derived_bucket, f"videos/{video.id}/clips/")
    context.storage.delete_prefix(context.derived_bucket, f"videos/{video.id}/thumbs/")

    created = []
    for window in windows:
        highlight = Highlight(
            id=uuid.uuid4(),
            match_id=video.match_id,
            start_time=window.start,
            end_time=window.end,
            score=window.candidate.score,
            type=window.candidate.type,
            signals={**window.candidate.signals, "detector": detector.name},
        )
        # Appended rather than added, so `video.highlights` is correct for
        # CUT_CLIPS without a reload.
        video.highlights.append(highlight)
        created.append(highlight)
    context.session.flush()

    logger.info(
        "pipeline.events_scored",
        extra={
            "detector": detector.name,
            "candidates": len(candidates),
            "selected": len(created),
        },
    )
    return {
        "detector": detector.name,
        "candidates": len(candidates),
        "selected": len(created),
        "top_score": max((h.score for h in created), default=0.0),
    }


@register_step(JobStep.CUT_CLIPS)
def cut_clips(context: StepContext) -> dict:
    """Cut one clip per highlight, from the replay rather than the 4K master.

    Partial failure is tolerated on purpose: one unreadable moment should cost
    that clip, not the whole match. Highlights that end up with no clip are
    pruned by PERSIST.
    """
    video = context.video
    highlights = sorted(video.highlights, key=lambda h: h.start_time)
    if not highlights:
        raise StepSkipped("there are no highlights to cut")

    source = readable(context, video.processed_url or video.original_url)
    cut = failed = vertical_cut = 0

    for highlight in highlights:
        duration = highlight.end_time - highlight.start_time
        if duration <= 0:
            continue
        try:
            clip = ffmpeg.cut_clip(
                source,
                context.workdir / f"clip-{highlight.id}.mp4",
                start=highlight.start_time,
                duration=duration,
            )
            highlight.video_url = context.storage.put_file(
                context.derived_bucket,
                keys.clip_key(video.id, highlight.id),
                clip,
                content_type="video/mp4",
            )
            cut += 1
        except ffmpeg.FFmpegError as exc:
            failed += 1
            logger.warning(
                "pipeline.clip_failed",
                extra={"highlight_id": str(highlight.id), "error": str(exc)[:200]},
            )
            continue

        if not context.settings.generate_vertical_clips:
            continue
        try:
            vertical = ffmpeg.cut_clip(
                source,
                context.workdir / f"clip-{highlight.id}-vertical.mp4",
                start=highlight.start_time,
                duration=duration,
                vertical=True,
            )
            highlight.video_url_vertical = context.storage.put_file(
                context.derived_bucket,
                keys.clip_key(video.id, highlight.id, vertical=True),
                vertical,
                content_type="video/mp4",
            )
            vertical_cut += 1
        except ffmpeg.FFmpegError as exc:
            # The 16:9 clip is the deliverable; the social crop is a bonus.
            logger.warning(
                "pipeline.vertical_clip_failed",
                extra={"highlight_id": str(highlight.id), "error": str(exc)[:200]},
            )

    context.session.flush()
    if cut == 0:
        raise StepError(f"every clip failed to cut ({failed} attempts)")

    logger.info(
        "pipeline.clips_cut", extra={"cut": cut, "vertical": vertical_cut, "failed": failed}
    )
    return {"cut": cut, "vertical": vertical_cut, "failed": failed}


@register_step(JobStep.THUMBNAILS)
def thumbnails(context: StepContext) -> dict:
    """One poster frame per clip.

    Skippable: without a thumbnail the player shows the clip's first frame, which
    is not worth failing a match over.
    """
    video = context.video
    highlights = [h for h in video.highlights if h.video_url]
    if not highlights:
        raise StepSkipped("there are no cut clips to take a thumbnail from")

    source = readable(context, video.processed_url or video.original_url)
    made = 0
    for highlight in highlights:
        # A third of the way in: past the build-up, into the action.
        at = highlight.start_time + (highlight.end_time - highlight.start_time) / 3
        try:
            image = ffmpeg.thumbnail(source, context.workdir / f"thumb-{highlight.id}.jpg", at=at)
            highlight.thumbnail_url = context.storage.put_file(
                context.derived_bucket,
                keys.thumbnail_key(video.id, highlight.id),
                image,
                content_type="image/jpeg",
            )
            made += 1
        except ffmpeg.FFmpegError as exc:
            logger.warning(
                "pipeline.thumbnail_failed",
                extra={"highlight_id": str(highlight.id), "error": str(exc)[:200]},
            )

    context.session.flush()
    logger.info("pipeline.thumbnails_made", extra={"thumbnails": made})
    return {"thumbnails": made, "of": len(highlights)}


@register_step(JobStep.PERSIST)
def persist(context: StepContext) -> dict:
    """Finalise: drop highlights that never got a clip, then mark the match READY.

    A highlight row with no clip is a broken card in the player's feed, so it is
    removed rather than shown. The runner sets the final statuses; this step
    records the numbers and the completion time.
    """
    video = context.video
    match = context.match

    orphans = [h for h in video.highlights if not h.video_url]
    for orphan in orphans:
        context.session.delete(orphan)
    context.session.flush()

    kept = [h for h in video.highlights if h.video_url]
    if not kept:
        raise StepError("no highlight survived clip generation")

    video.status = VideoStatus.READY
    video.failure_reason = None
    if match is not None:
        match.status = MatchStatus.READY
        match.failure_reason = None
    video.video_metadata = {
        **(video.video_metadata or {}),
        "completed_at": utcnow().isoformat(),
        "highlight_count": len(kept),
    }
    context.session.flush()

    logger.info(
        "pipeline.persisted",
        extra={"highlights": len(kept), "dropped": len(orphans), "match_id": str(video.match_id)},
    )
    return {
        "highlights": len(kept),
        "dropped": len(orphans),
        "with_vertical": sum(1 for h in kept if h.video_url_vertical),
        "with_thumbnail": sum(1 for h in kept if h.thumbnail_url),
    }
