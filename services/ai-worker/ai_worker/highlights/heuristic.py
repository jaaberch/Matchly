"""The detector that reads player tracks.

Top of the ladder. It fuses the signals in :mod:`.signals` into a score per
second, then hands the peaks back as candidates. What makes it better than the
motion fallback is not cleverness — it is that it knows *where the players are*,
so it can tell a scramble in the six-yard box from a goalkeeper's long kick, and
both from the camera being nudged.

Registered at a high priority but gated on tracks existing. A worker without the
CV runtime never registers it at all, and the ladder falls through.
"""

from __future__ import annotations

from matchly_shared.config import Settings, get_settings
from matchly_shared.domain import HighlightType
from matchly_shared.highlights import (
    Candidate,
    DetectionRequest,
    HighlightDetector,
    register_detector,
)
from matchly_shared.logging import get_logger

from .signals import GRID_SECONDS, SignalContext, compute_signals, fuse

logger = get_logger(__name__)

#: A peak must clear its neighbours to count as a moment rather than a plateau.
PEAK_MARGIN = 0.02


class HeuristicHighlightDetector(HighlightDetector):
    name = "heuristic-v1"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def detect(self, request: DetectionRequest) -> list[Candidate]:
        context = SignalContext(
            tracks=request.tracks,
            duration=request.duration,
            has_audio=request.has_audio,
        )
        computed = compute_signals(context)
        if not computed:
            return []

        fused = fuse(computed, self._settings.signal_weights, buckets=context.buckets())
        if not fused:
            return []

        candidates = [
            Candidate(
                timestamp=timestamp,
                score=score,
                signals=contributions,
                type=_classify(contributions),
            )
            for timestamp, score, contributions in _peaks(fused)
        ]

        logger.info(
            "highlights.heuristic_scored",
            extra={
                "signals": sorted(computed),
                "buckets": len(fused),
                "candidates": len(candidates),
                "tracks": len({sample.track_ref for sample in request.tracks}),
            },
        )
        return candidates


def _peaks(
    fused: list[tuple[float, float, dict[str, float]]],
) -> list[tuple[float, float, dict[str, float]]]:
    """Local maxima only.

    Without this, a busy thirty seconds contributes thirty near-identical
    candidates and the overlap suppression downstream has to throw most of them
    away. Cheaper to not create them.
    """
    if len(fused) < 3:
        return fused

    peaks = []
    for index, (timestamp, score, contributions) in enumerate(fused):
        previous = fused[index - 1][1] if index > 0 else -1.0
        following = fused[index + 1][1] if index + 1 < len(fused) else -1.0
        if score >= previous + PEAK_MARGIN and score >= following:
            peaks.append((timestamp, score, contributions))
    return peaks or fused


def _classify(contributions: dict[str, float]) -> HighlightType:
    """Name the moment from whichever signal dominates it.

    Rough by construction: these are correlates, not events. A real event model
    would replace both the scoring and this labelling.
    """
    if not contributions:
        return HighlightType.GENERIC
    dominant = max(contributions, key=contributions.get)
    return {
        "player_density": HighlightType.GOAL_AREA_ACTION,
        "clustering": HighlightType.CELEBRATION,
        "audio_peak": HighlightType.CELEBRATION,
        "acceleration": HighlightType.HIGH_INTENSITY,
        "motion": HighlightType.HIGH_INTENSITY,
        "direction_change": HighlightType.TEAM_BUILDUP,
    }.get(dominant, HighlightType.GENERIC)


def _has_tracks(request: DetectionRequest) -> bool:
    return request.has_tracks


@register_detector("heuristic", priority=100, supports=_has_tracks)
def _build_heuristic() -> HeuristicHighlightDetector:
    return HeuristicHighlightDetector()


__all__ = ["GRID_SECONDS", "HeuristicHighlightDetector"]
