"""Thin, typed wrappers around ffmpeg and ffprobe.

Every call is a subprocess with an explicit timeout: a wedged ffmpeg must not
hold a worker slot forever. Nothing here touches the database or object storage —
these functions take paths and URLs and return data, which keeps them testable
against a three-second clip generated on the fly.

ffmpeg reads HTTP sources natively, so a probe or transcode can stream straight
from a signed URL instead of copying an 8–30 GB master to local disk first.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from matchly_shared.logging import get_logger

logger = get_logger(__name__)

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

#: Generous, because a 60-minute 4K transcode is genuinely slow; still bounded.
DEFAULT_TIMEOUT = 60 * 60


class FFmpegError(RuntimeError):
    """ffmpeg or ffprobe exited non-zero, timed out, or is not installed."""


def available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run(command: list[str], *, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    logger.debug("ffmpeg.run", extra={"command": " ".join(command[:8])})
    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, arguments built here
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:
        raise FFmpegError(
            "ffmpeg is not installed in this worker image. "
            "The worker image installs it; the API image deliberately does not."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"timed out after {timeout}s: {' '.join(command[:6])}") from exc

    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-6:]
        raise FFmpegError(f"exit {result.returncode}: {' | '.join(tail)}")
    return result


# ── Probing ──────────────────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True, slots=True)
class MediaInfo:
    duration: float | None
    width: int | None
    height: int | None
    fps: float | None
    has_audio: bool
    video_codec: str | None = None
    audio_codec: str | None = None
    bit_rate: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _parse_fraction(value: str | None) -> float | None:
    """ffprobe reports frame rates as ``30000/1001``, not as a float."""
    if not value:
        return None
    try:
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            return round(float(numerator) / denominator_value, 4)
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def parse_probe(payload: dict[str, Any]) -> MediaInfo:
    """Turn raw ffprobe JSON into the handful of fields the platform needs.

    Kept separate from the subprocess call so the parsing rules — fractional
    frame rates, missing streams, rotated video — are unit-testable without
    ffmpeg installed.
    """
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    container = payload.get("format") or {}

    duration = container.get("duration") or (video or {}).get("duration")
    try:
        duration_value = round(float(duration), 3) if duration is not None else None
    except (TypeError, ValueError):
        duration_value = None

    width = height = None
    if video is not None:
        width, height = video.get("width"), video.get("height")
        # A phone-shot clip can carry a 90° rotation; swap so the stored
        # dimensions match what a viewer actually sees.
        rotation = _rotation(video)
        if rotation in (90, 270) and width and height:
            width, height = height, width

    try:
        bit_rate = int(container["bit_rate"]) if container.get("bit_rate") else None
    except (TypeError, ValueError):
        bit_rate = None

    return MediaInfo(
        duration=duration_value,
        width=width,
        height=height,
        fps=_parse_fraction((video or {}).get("avg_frame_rate"))
        or _parse_fraction((video or {}).get("r_frame_rate")),
        has_audio=audio is not None,
        video_codec=(video or {}).get("codec_name"),
        audio_codec=(audio or {}).get("codec_name"),
        bit_rate=bit_rate,
    )


def _rotation(stream: dict[str, Any]) -> int:
    for side_data in stream.get("side_data_list") or []:
        if "rotation" in side_data:
            try:
                return abs(int(side_data["rotation"])) % 360
            except (TypeError, ValueError):
                continue
    tags = stream.get("tags") or {}
    try:
        return abs(int(tags.get("rotate", 0))) % 360
    except (TypeError, ValueError):
        return 0


def probe(source: str | Path, *, timeout: int = 120) -> tuple[MediaInfo, dict[str, Any]]:
    """Run ffprobe on a path or URL. Returns parsed info and the raw payload."""
    result = _run(
        [
            FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(source),
        ],
        timeout=timeout,
    )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FFmpegError("ffprobe returned output that is not JSON") from exc
    if not payload.get("streams"):
        raise FFmpegError("no media streams found — the file is not a readable recording")
    return parse_probe(payload), payload


# ── Transforms ───────────────────────────────────────────────────────────
def concat(segments: list[Path], output: Path, *, timeout: int = DEFAULT_TIMEOUT) -> Path:
    """Join uploaded segments into one master, without re-encoding.

    Stream copy, so joining an hour of 4K costs seconds rather than an hour of
    CPU, and the original bytes are preserved exactly.
    """
    if not segments:
        raise FFmpegError("no segments to join")
    listing = output.parent / "segments.txt"
    listing.write_text("".join(f"file '{path.resolve()}'\n" for path in segments))
    _run(
        [
            FFMPEG,
            "-nostdin",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(output),
        ],
        timeout=timeout,
    )
    return output


def transcode(
    source: str | Path,
    output: Path,
    *,
    height: int,
    crf: int = 23,
    preset: str = "veryfast",
    with_audio: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> Path:
    """Re-encode to a target height, preserving aspect ratio."""
    command = [
        FFMPEG,
        "-nostdin",
        "-y",
        "-i",
        str(source),
        # -2 keeps the width even, which H.264 requires.
        "-vf",
        f"scale=-2:{height}",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",  # so the browser can start playing immediately
    ]
    command += ["-c:a", "aac", "-b:a", "128k"] if with_audio else ["-an"]
    command.append(str(output))
    _run(command, timeout=timeout)
    return output


def extract_frames(
    source: str | Path,
    output_dir: Path,
    *,
    fps: float = 2.0,
    width: int = 640,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[Path]:
    """Sample frames for the CV steps.

    Running detection on every 4K frame is roughly 100x the compute budget; two
    frames a second from a downscaled proxy is what makes this affordable.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    _run(
        [
            FFMPEG,
            "-nostdin",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"fps={fps},scale={width}:-2",
            "-q:v",
            "3",
            str(output_dir / "%06d.jpg"),
        ],
        timeout=timeout,
    )
    return sorted(output_dir.glob("*.jpg"))


def cut_clip(
    source: str | Path,
    output: Path,
    *,
    start: float,
    duration: float,
    vertical: bool = False,
    timeout: int = 600,
) -> Path:
    """Cut one highlight.

    ``-ss`` before ``-i`` seeks by keyframe, which is fast but imprecise; putting
    it after re-encodes from an exact position. Highlights are short and need to
    start on the right moment, so precision wins.
    """
    command = [
        FFMPEG,
        "-nostdin",
        "-y",
        "-ss",
        str(max(0.0, start)),
        "-i",
        str(source),
        "-t",
        str(duration),
    ]
    if vertical:
        # Centre-crop to 9:16 for social. Phase 6 can follow the action instead.
        command += ["-vf", "crop=ih*9/16:ih,scale=1080:1920"]
    command += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(output),
    ]
    _run(command, timeout=timeout)
    return output


def thumbnail(
    source: str | Path, output: Path, *, at: float = 0.0, width: int = 640, timeout: int = 120
) -> Path:
    _run(
        [
            FFMPEG,
            "-nostdin",
            "-y",
            "-ss",
            str(max(0.0, at)),
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            str(output),
        ],
        timeout=timeout,
    )
    return output


def make_test_video(
    output: Path, *, seconds: int = 5, width: int = 320, height: int = 240, fps: int = 10
) -> Path:
    """Generate a synthetic clip. Used by the test suite and by `make demo`."""
    _run(
        [
            FFMPEG,
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={seconds}:size={width}x{height}:rate={fps}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ],
        timeout=300,
    )
    return output
