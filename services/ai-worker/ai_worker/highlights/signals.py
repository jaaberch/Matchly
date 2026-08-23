"""The signals that say a moment was worth watching.

Each signal is an independent function from player tracks to a series of scores
over time. They are deliberately separate and individually optional: a pitch
camera with no microphone simply has no audio signal, a match where tracking
failed has only motion, and the fusion copes with either by renormalising over
whatever it was given.

None of this is football *understanding*. It is a set of correlates — players
moving fast, players crowded near a goal, everyone converging on one spot — that
happen to coincide with the moments people want to watch. A trained event model
would be better, and slots in behind the same detector interface.
"""

from __future__ import annotations

import dataclasses
import math
import statistics
from collections.abc import Callable

from matchly_shared.highlights import TrackSample
from matchly_shared.logging import get_logger

logger = get_logger(__name__)

#: Scores are produced on a fixed grid so signals of different natural
#: resolutions can be summed.
GRID_SECONDS = 1.0

#: A fixed wide camera puts the goals at the left and right edges. Without
#: per-field calibration this is the best available guess, and it is the first
#: thing worth replacing: marking the goal mouths per field would sharpen the
#: density signal considerably.
GOAL_BAND = 0.22

Series = dict[int, float]  # grid bucket -> 0..1


@dataclasses.dataclass(frozen=True, slots=True)
class SignalContext:
    tracks: list[TrackSample]
    duration: float
    has_audio: bool
    #: RMS energy per grid bucket, when the audio pass ran.
    audio: Series | None = None

    def buckets(self) -> int:
        return max(1, int(math.ceil(self.duration / GRID_SECONDS)))


SignalFn = Callable[[SignalContext], Series]
_SIGNALS: dict[str, SignalFn] = {}


def signal(name: str) -> Callable[[SignalFn], SignalFn]:
    def decorator(function: SignalFn) -> SignalFn:
        _SIGNALS[name] = function
        return function

    return decorator


def _bucket(timestamp: float) -> int:
    return int(timestamp // GRID_SECONDS)


def _normalise(raw: dict[int, float]) -> Series:
    """Scale a raw series into 0..1 against its own distribution.

    Relative rather than absolute, because what counts as "fast" depends on the
    pitch size, the camera height and the standard of play. A match is scored
    against itself.
    """
    if not raw:
        return {}
    values = list(raw.values())
    if len(values) < 2:
        return dict.fromkeys(raw, 0.5)
    low = min(values)
    high = max(values)
    if high - low < 1e-9:
        return dict.fromkeys(raw, 0.5)
    return {bucket: round((value - low) / (high - low), 3) for bucket, value in raw.items()}


def _by_track(tracks: list[TrackSample]) -> dict[str, list[TrackSample]]:
    grouped: dict[str, list[TrackSample]] = {}
    for sample in tracks:
        grouped.setdefault(sample.track_ref, []).append(sample)
    for samples in grouped.values():
        samples.sort(key=lambda sample: sample.timestamp)
    return grouped


def _velocities(samples: list[TrackSample]) -> list[tuple[float, float, float]]:
    """``(timestamp, speed, heading)`` between consecutive samples."""
    out: list[tuple[float, float, float]] = []
    for previous, current in zip(samples, samples[1:], strict=False):
        dt = current.timestamp - previous.timestamp
        if dt <= 0:
            continue
        dx = (current.x - previous.x) / dt
        dy = (current.y - previous.y) / dt
        out.append((current.timestamp, math.hypot(dx, dy), math.atan2(dy, dx)))
    return out


# ── Signals ──────────────────────────────────────────────────────────────
@signal("motion")
def motion(context: SignalContext) -> Series:
    """How fast the players are moving, summed across everyone on the pitch."""
    raw: dict[int, float] = {}
    for samples in _by_track(context.tracks).values():
        for timestamp, speed, _ in _velocities(samples):
            raw[_bucket(timestamp)] = raw.get(_bucket(timestamp), 0.0) + speed
    return _normalise(raw)


@signal("acceleration")
def acceleration(context: SignalContext) -> Series:
    """Sudden changes of pace — a sprint starting, a player checking back.

    Often a better marker than speed itself: a match spends long stretches at a
    steady jog, and the interesting moments are where that breaks.
    """
    raw: dict[int, float] = {}
    for samples in _by_track(context.tracks).values():
        velocities = _velocities(samples)
        for (t0, v0, _), (t1, v1, _) in zip(velocities, velocities[1:], strict=False):
            dt = t1 - t0
            if dt <= 0:
                continue
            raw[_bucket(t1)] = raw.get(_bucket(t1), 0.0) + abs(v1 - v0) / dt
    return _normalise(raw)


@signal("player_density")
def player_density(context: SignalContext) -> Series:
    """How many players are inside either goal area.

    The strongest single correlate of a chance, and the reason the goal bands are
    worth calibrating per field.
    """
    raw: dict[int, float] = {}
    for sample in context.tracks:
        near_goal = sample.x <= GOAL_BAND or sample.x >= 1.0 - GOAL_BAND
        if near_goal:
            raw[_bucket(sample.timestamp)] = raw.get(_bucket(sample.timestamp), 0.0) + 1.0
    return _normalise(raw)


@signal("direction_change")
def direction_change(context: SignalContext) -> Series:
    """Turning. A scramble in the box turns constantly; a goal kick does not."""
    raw: dict[int, float] = {}
    for samples in _by_track(context.tracks).values():
        velocities = _velocities(samples)
        for (_, _, h0), (t1, _, h1) in zip(velocities, velocities[1:], strict=False):
            delta = abs(math.atan2(math.sin(h1 - h0), math.cos(h1 - h0)))
            raw[_bucket(t1)] = raw.get(_bucket(t1), 0.0) + delta
    return _normalise(raw)


@signal("clustering")
def clustering(context: SignalContext) -> Series:
    """Players converging on one spot — a celebration, or a melee.

    Measured as the inverse spread of everyone's positions, so a tight knot
    scores high and a spread-out pitch scores low.
    """
    positions: dict[int, list[tuple[float, float]]] = {}
    for sample in context.tracks:
        positions.setdefault(_bucket(sample.timestamp), []).append((sample.x, sample.y))

    raw: dict[int, float] = {}
    for bucket, points in positions.items():
        if len(points) < 4:
            continue
        centre_x = statistics.fmean(x for x, _ in points)
        centre_y = statistics.fmean(y for _, y in points)
        spread = statistics.fmean(math.hypot(x - centre_x, y - centre_y) for x, y in points)
        raw[bucket] = 1.0 / (spread + 0.05)
    return _normalise(raw)


@signal("audio_peak")
def audio_peak(context: SignalContext) -> Series:
    """Shouting. Only available when the camera has a microphone."""
    if not context.has_audio or not context.audio:
        return {}
    return _normalise(dict(context.audio))


# ── Fusion ───────────────────────────────────────────────────────────────
def compute_signals(context: SignalContext) -> dict[str, Series]:
    """Every signal that produced anything for this recording."""
    computed: dict[str, Series] = {}
    for name, function in _SIGNALS.items():
        try:
            series = function(context)
        except Exception as exc:  # one bad signal must not lose the match
            logger.warning("signals.failed", extra={"signal": name, "error": str(exc)[:200]})
            continue
        if series:
            computed[name] = series
    return computed


def fuse(
    computed: dict[str, Series], weights: dict[str, float], *, buckets: int
) -> list[tuple[float, float, dict[str, float]]]:
    """Combine signals into one score per bucket.

    Weights are renormalised over the signals that actually produced data, so a
    silent camera does not quietly cap every score at 0.9 — the remaining signals
    simply carry more of the decision.
    """
    active = {name: weights.get(name, 0.0) for name in computed}
    total_weight = sum(active.values())
    if total_weight <= 0:
        return []

    fused: list[tuple[float, float, dict[str, float]]] = []
    for bucket in range(buckets):
        contributions = {name: series.get(bucket, 0.0) for name, series in computed.items()}
        if not any(contributions.values()):
            continue
        score = sum(contributions[name] * weight for name, weight in active.items()) / total_weight
        fused.append(
            (
                bucket * GRID_SECONDS + GRID_SECONDS / 2,
                round(min(0.99, score), 3),
                {name: round(value, 2) for name, value in contributions.items() if value > 0},
            )
        )
    return fused


def registered_signals() -> list[str]:
    return sorted(_SIGNALS)
