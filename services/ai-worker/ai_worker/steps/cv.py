"""The computer-vision pipeline steps.

All three are optional. A worker without the CV runtime never registers them, a
model that fails to load raises, and either way the match still reaches READY
with motion-based highlights. That is the whole contract: **the AI is an
enhancement, never a dependency.**

They run as a group within one pipeline pass and hand intermediate results to
each other through the run's scratch directory, because the alternative —
persisting a hundred thousand bounding boxes per match — would cost more than the
detection itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from matchly_shared.domain import JobStep, MatchPlayer, PlayerTrack
from matchly_shared.logging import get_logger
from matchly_shared.pipeline import StepContext, StepSkipped, register_step
from matchly_shared.storage import parse_uri

from ..detection import FrameDetections, ModelUnavailable, YoloPlayerDetector
from ..detection.base import Box
from ..jersey import build_recognizer, choose_moments, extract_crops, vote
from ..jersey.voting import JerseyRead
from ..tracking import ByteTracker, Track
from ..tracking.base import TrackPoint

logger = get_logger(__name__)

DETECTIONS_FILE = "detections.json"
TRACKS_FILE = "tracks.json"

#: Positions kept per track when persisting. The scoring grid is one second, so
#: more than this buys nothing and bloats the row.
MAX_PERSISTED_SAMPLES = 240


# ── helpers ──────────────────────────────────────────────────────────────
def _readable(context: StepContext, uri: str | None) -> str | Path:
    if not uri:
        raise StepSkipped("nothing to read")
    ref = parse_uri(uri)
    local = context.storage.local_path(ref.bucket, ref.key)
    if local is not None:
        return local
    return context.storage.signed_download_url(
        ref.bucket, ref.key, ttl_seconds=context.settings.signed_url_ttl_seconds
    )


def _sample_frames(context: StepContext) -> tuple[list[Path], float]:
    """Frames for detection, sampled here rather than inherited.

    SAMPLE_FRAMES may have run in a different process whose scratch directory is
    long gone, so this step takes responsibility for its own input. The proxy is
    small; re-sampling it costs seconds.
    """
    from video_worker import ffmpeg

    frames_dir = context.workdir / "frames"
    existing = sorted(frames_dir.glob("*.jpg")) if frames_dir.is_dir() else []
    if existing:
        return existing, context.settings.frame_sample_fps

    if not context.video.proxy_url:
        raise StepSkipped("no proxy was produced, so there is nothing to look at")

    frames = ffmpeg.extract_frames(
        _readable(context, context.video.proxy_url),
        frames_dir,
        fps=context.settings.frame_sample_fps,
        width=context.settings.proxy_height,
    )
    return frames, context.settings.frame_sample_fps


# ── DETECT_PLAYERS ───────────────────────────────────────────────────────
@register_step(JobStep.DETECT_PLAYERS)
def detect_players(context: StepContext) -> dict:
    """Find the players in each sampled frame."""
    frames, fps = _sample_frames(context)
    if not frames:
        raise StepSkipped("the proxy yielded no frames")

    limit = context.settings.max_detection_frames
    if len(frames) > limit:
        # Thin evenly rather than truncate: half a match detected is worse than
        # a whole match detected at a coarser cadence.
        stride = len(frames) / limit
        frames = [frames[int(index * stride)] for index in range(limit)]
        fps = fps / stride
        logger.info("detection.thinned", extra={"kept": len(frames), "effective_fps": fps})

    detector = YoloPlayerDetector(
        weights=context.settings.yolo_weights,
        confidence=context.settings.yolo_confidence,
        image_size=context.settings.yolo_image_size,
        batch_size=context.settings.yolo_batch_size,
    )
    try:
        results = detector.detect(frames, fps=fps)
    except ModelUnavailable as exc:
        # The documented degradation: no model, no attribution, still a match.
        raise StepSkipped(str(exc)) from exc

    payload = [
        {
            "frame_index": item.frame_index,
            "timestamp": round(item.timestamp, 3),
            "boxes": [
                [
                    round(b.x1, 1),
                    round(b.y1, 1),
                    round(b.x2, 1),
                    round(b.y2, 1),
                    round(b.confidence, 3),
                ]
                for b in item.boxes
            ],
        }
        for item in results
    ]
    (context.workdir / DETECTIONS_FILE).write_text(json.dumps(payload))

    total = sum(item.count for item in results)
    return {
        "detector": detector.name,
        "frames": len(frames),
        "detections": total,
        "mean_per_frame": round(total / max(len(frames), 1), 2),
        "fps": round(fps, 3),
    }


# ── TRACK ────────────────────────────────────────────────────────────────
@register_step(JobStep.TRACK)
def track_players(context: StepContext) -> dict:
    """Follow each player across frames and persist the tracks."""
    detections_path = context.workdir / DETECTIONS_FILE
    if not detections_path.is_file():
        raise StepSkipped("detection did not run in this pass, so there is nothing to track")

    payload = json.loads(detections_path.read_text())
    frames = [
        FrameDetections(
            frame_index=item["frame_index"],
            timestamp=item["timestamp"],
            boxes=[Box(x1=b[0], y1=b[1], x2=b[2], y2=b[3], confidence=b[4]) for b in item["boxes"]],
        )
        for item in payload
    ]

    tracker = ByteTracker()
    tracks = tracker.track(frames)
    if not tracks:
        raise StepSkipped("no player held together across enough frames to track")

    _persist_tracks(context, tracks)
    (context.workdir / TRACKS_FILE).write_text(
        json.dumps(
            [
                {
                    "ref": track.ref,
                    "points": [
                        [round(p.timestamp, 3), *[round(v, 1) for v in p.box.as_tuple()]]
                        for p in track.points
                    ],
                }
                for track in tracks
            ]
        )
    )

    return {
        "tracker": tracker.name,
        "tracks": len(tracks),
        "mean_length": round(sum(t.length for t in tracks) / len(tracks), 1),
        "longest_seconds": round(max(t.duration for t in tracks), 1),
    }


def _persist_tracks(context: StepContext, tracks: list[Track]) -> None:
    """Write PlayerTrack rows, replacing any from a previous run."""
    session = context.session
    for existing in list(context.video.tracks):
        session.delete(existing)
    session.flush()
    session.expire(context.video, ["tracks"])

    width = float(context.video.width or 1) or 1.0
    height = float(context.video.height or 1) or 1.0
    # Detection ran on the proxy; positions are stored normalised so nothing
    # downstream has to know either resolution.
    proxy_width = width
    proxy_height = height

    for track in tracks:
        points = track.points
        if len(points) > MAX_PERSISTED_SAMPLES:
            stride = len(points) / MAX_PERSISTED_SAMPLES
            points = [points[int(i * stride)] for i in range(MAX_PERSISTED_SAMPLES)]

        context.video.tracks.append(
            PlayerTrack(
                video_id=context.video.id,
                track_ref=track.ref,
                first_seen=round(track.first_seen, 3),
                last_seen=round(track.last_seen, 3),
                samples={
                    "positions": [
                        [
                            round(point.timestamp, 2),
                            round(point.box.centre[0] / proxy_width, 4),
                            round(point.box.centre[1] / proxy_height, 4),
                            round(point.box.width / proxy_width, 4),
                            round(point.box.height / proxy_height, 4),
                        ]
                        for point in points
                    ]
                },
            )
        )
    session.flush()


# ── JERSEY_OCR ───────────────────────────────────────────────────────────
@register_step(JobStep.JERSEY_OCR)
def read_jerseys(context: StepContext) -> dict:
    """Read shirt numbers and attribute tracks to registered players.

    Crops come from the master, not the proxy: a player is a few dozen pixels
    tall on the proxy and the number is unreadable. See
    :mod:`ai_worker.jersey.base`.
    """
    tracks_path = context.workdir / TRACKS_FILE
    if not tracks_path.is_file():
        raise StepSkipped("tracking did not run in this pass")

    recognizer = build_recognizer()
    if recognizer.name == "null":
        raise StepSkipped("no OCR runtime is installed; highlights will be delivered unattributed")

    registered = _registered_numbers(context)
    if not registered:
        raise StepSkipped("nobody checked in, so there are no numbers to match against")

    payload = json.loads(tracks_path.read_text())
    tracks = [
        Track(
            ref=item["ref"],
            points=[
                TrackPoint(
                    frame_index=index,
                    timestamp=point[0],
                    box=Box(x1=point[1], y1=point[2], x2=point[3], y2=point[4], confidence=1.0),
                )
                for index, point in enumerate(item["points"])
            ],
        )
        for item in payload
    ]

    master = _readable(context, context.video.original_url)
    scale = _master_scale(context)

    attributed = 0
    read_total = 0
    by_track: dict[str, list[JerseyRead]] = {}

    for track in tracks:
        moments = choose_moments(track, limit=context.settings.jersey_crops_per_track)
        crops = extract_crops(master, moments, scale=scale)
        if not crops:
            continue
        for track_ref, number, confidence in recognizer.read(crops):
            by_track.setdefault(track_ref, []).append(
                JerseyRead(number=number, confidence=confidence)
            )
            read_total += 1

    stored = {row.track_ref: row for row in context.video.tracks}
    for track_ref, reads in by_track.items():
        verdict = vote(
            reads,
            allowed_numbers=set(registered),
            min_votes=context.settings.jersey_min_votes,
            min_share=context.settings.jersey_min_share,
            min_margin=context.settings.jersey_min_margin,
        )
        row = stored.get(track_ref)
        if row is None:
            continue
        row.samples = {**(row.samples or {}), "jersey_votes": verdict.distribution}
        if not verdict.attributed:
            logger.info(
                "jersey.unattributed",
                extra={"track_ref": track_ref, "reason": verdict.rejection},
            )
            continue
        row.jersey_number = verdict.number
        row.jersey_confidence = verdict.confidence
        row.player_id = registered[verdict.number]
        attributed += 1

    context.session.flush()
    return {
        "recognizer": recognizer.name,
        "tracks_examined": len(tracks),
        "reads": read_total,
        "attributed": attributed,
    }


def _registered_numbers(context: StepContext) -> dict[int, object]:
    """Shirt number to MatchPlayer id, for the numbers actually on the pitch.

    Constraining the answer to registered numbers is worth more than any model
    change: it turns a hundred-way guess into a choice among the dozen numbers
    that exist, and discards a read of "38" when nobody wears 38.

    A number worn by two players — the administrator override at check-in — is
    excluded, because there is no way to tell those two apart.
    """
    rows = context.session.scalars(
        select(MatchPlayer).where(MatchPlayer.match_id == context.video.match_id)
    ).all()
    counts: dict[int, int] = {}
    for row in rows:
        counts[row.jersey_number] = counts.get(row.jersey_number, 0) + 1
    return {row.jersey_number: row.id for row in rows if counts[row.jersey_number] == 1}


def _master_scale(context: StepContext) -> float:
    """How much bigger the master is than the proxy, in width."""
    master_width = context.video.width or 0
    proxy_height = context.settings.proxy_height
    master_height = context.video.height or 0
    if not master_width or not master_height or not proxy_height:
        return 1.0
    effective_proxy_height = min(proxy_height, master_height)
    return master_height / max(effective_proxy_height, 1)
