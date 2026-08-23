"""TRANSCODE and SAMPLE_FRAMES — turning a 4K master into things we can use."""

from __future__ import annotations

from matchly_shared.domain import JobStep
from matchly_shared.logging import get_logger
from matchly_shared.pipeline import StepContext, StepError, StepSkipped, register_step
from matchly_shared.storage import keys

from .. import ffmpeg
from ._source import master_source, proxy_source

logger = get_logger(__name__)


@register_step(JobStep.TRANSCODE)
def transcode(context: StepContext) -> dict:
    """Produce the two derivatives everything else uses.

    * **replay** — what players actually watch. 1080p with a moved-forward
      index so a browser starts playing without downloading the whole file.
    * **proxy** — 640p, for the CV steps. Detection on full 4K is roughly a
      hundred times the compute budget and buys nothing for the signals the
      scorer needs.

    Neither is ever upscaled past the source: a 720p camera stays 720p.
    """
    video = context.video
    if not video.height:
        raise StepError("cannot transcode before the recording has been probed")

    source = master_source(context)
    settings = context.settings

    replay_height = min(settings.replay_height, video.height)
    replay_path = ffmpeg.transcode(
        source,
        context.workdir / "replay.mp4",
        height=replay_height,
        crf=settings.transcode_crf,
        preset=settings.transcode_preset,
        with_audio=video.has_audio,
    )
    video.processed_url = context.storage.put_file(
        context.derived_bucket,
        keys.replay_key(video.id),
        replay_path,
        content_type="video/mp4",
    )

    proxy_height = min(settings.proxy_height, video.height)
    proxy_path = ffmpeg.transcode(
        source,
        context.workdir / "proxy.mp4",
        height=proxy_height,
        crf=28,  # the proxy is machine-read; quality matters far less than size
        preset="veryfast",
        with_audio=False,
    )
    video.proxy_url = context.storage.put_file(
        context.derived_bucket,
        keys.proxy_key(video.id),
        proxy_path,
        content_type="video/mp4",
    )

    logger.info(
        "pipeline.transcoded",
        extra={
            "replay_height": replay_height,
            "proxy_height": proxy_height,
            "replay_bytes": replay_path.stat().st_size,
            "proxy_bytes": proxy_path.stat().st_size,
        },
    )
    return {
        "replay_height": replay_height,
        "proxy_height": proxy_height,
        "replay_bytes": replay_path.stat().st_size,
        "proxy_bytes": proxy_path.stat().st_size,
    }


@register_step(JobStep.SAMPLE_FRAMES)
def sample_frames(context: StepContext) -> dict:
    """Sample frames from the proxy for the detection steps.

    Frames stay in the run's scratch directory rather than object storage: a
    60-minute match at 2 fps is about 7,200 files, and writing those as objects
    would cost far more than re-sampling the one small proxy when needed.

    Skippable. Without frames the scorer falls back to what it can measure from
    the recording as a whole, and the match still reaches READY.
    """
    if not context.video.proxy_url:
        raise StepSkipped("no proxy was produced")

    frames = ffmpeg.extract_frames(
        proxy_source(context),
        context.workdir / "frames",
        fps=context.settings.frame_sample_fps,
        width=context.settings.proxy_height,
    )
    if not frames:
        raise StepSkipped("the proxy yielded no frames")

    logger.info("pipeline.frames_sampled", extra={"frames": len(frames)})
    return {"frames": len(frames), "fps": context.settings.frame_sample_fps}
