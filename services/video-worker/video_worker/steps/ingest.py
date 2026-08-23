"""VALIDATE and PROBE — everything downstream depends on these two."""

from __future__ import annotations

from matchly_shared.domain import JobStep
from matchly_shared.logging import get_logger
from matchly_shared.pipeline import StepContext, StepError, register_step
from matchly_shared.storage import ObjectNotFound, keys, parse_uri

from .. import ffmpeg
from ._source import download, master_source

logger = get_logger(__name__)

#: Below this a "recording" is a truncated upload, not a match.
MIN_PLAUSIBLE_BYTES = 1024


@register_step(JobStep.VALIDATE)
def validate(context: StepContext) -> dict:
    """Confirm the recording exists and is one readable file.

    Segments are joined here, by stream copy, so every later step has a single
    master to work from. The join is a copy rather than a re-encode: an hour of
    4K costs seconds and the original bytes survive untouched.

    Originals are write-once. This step writes the joined master under a
    deterministic key, so a retry overwrites its own output rather than leaving
    a second copy behind.
    """
    video = context.video
    bucket = context.originals_bucket

    if video.original_url:
        ref = parse_uri(video.original_url)
        try:
            info = context.storage.stat(ref.bucket, ref.key)
        except ObjectNotFound as exc:
            raise StepError(f"the recording is not in storage: {ref.bucket}/{ref.key}") from exc
        if info.size < MIN_PLAUSIBLE_BYTES:
            raise StepError(f"the recording is only {info.size} bytes — it is truncated")
        video.size_bytes = info.size
        return {"source": "master", "size_bytes": info.size}

    segments = sorted(video.segments, key=lambda segment: segment.segment_index)
    if not segments:
        raise StepError("no recording was uploaded for this match")

    indexes = [segment.segment_index for segment in segments]
    expected = list(range(len(segments)))
    if indexes != expected:
        # A gap means the agent has not finished uploading. Failing here is
        # right: joining around a hole would silently lose minutes of play.
        missing = sorted(set(range(max(indexes) + 1)) - set(indexes))
        raise StepError(f"segments are missing: {missing[:20]}")

    local_segments = []
    for segment in segments:
        destination = context.workdir / f"segment-{segment.segment_index:05d}.mp4"
        local_segments.append(download(context, segment.storage_url, destination))

    joined = ffmpeg.concat(local_segments, context.workdir / "master.mp4")
    key = keys.master_key(video.match_id, video.id)
    video.original_url = context.storage.put_file(bucket, key, joined, content_type="video/mp4")
    video.size_bytes = joined.stat().st_size

    logger.info(
        "pipeline.segments_joined",
        extra={"segments": len(segments), "size_bytes": video.size_bytes},
    )
    return {"source": "segments", "segments": len(segments), "size_bytes": video.size_bytes}


@register_step(JobStep.PROBE)
def probe(context: StepContext) -> dict:
    """Read the recording's real duration, resolution, frame rate and audio.

    Every later decision uses these: how far to downscale, where clips may start,
    whether an audio signal is available at all.
    """
    info, raw = ffmpeg.probe(master_source(context))

    if not info.duration or info.duration <= 0:
        raise StepError("the recording reports no duration — it is unplayable")
    if not info.width or not info.height:
        raise StepError("the recording has no video stream")

    video = context.video
    video.duration = info.duration
    video.width = info.width
    video.height = info.height
    video.fps = info.fps
    video.has_audio = info.has_audio
    video.video_metadata = {
        **(video.video_metadata or {}),
        "probe": info.as_dict(),
        "format": raw.get("format", {}).get("format_name"),
    }

    logger.info(
        "pipeline.probed",
        extra={
            "duration": info.duration,
            "resolution": f"{info.width}x{info.height}",
            "fps": info.fps,
            "has_audio": info.has_audio,
        },
    )
    return info.as_dict()
