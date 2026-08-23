"""A stand-in detector, so the end-to-end flow can ship before any CV exists.

This does **not** watch the football. It spreads plausible-looking candidates
across the recording, deterministically seeded by video id so a re-run produces
the same clips and the pipeline's idempotency can actually be tested.

It exists to prove the whole chain — record, upload, process, cut, deliver —
works. Phase 5 replaces it with the heuristic detector behind the same
interface; nothing downstream changes.
"""

from __future__ import annotations

import random

from matchly_shared.domain import HighlightType

from .base import Candidate, DetectionRequest, HighlightDetector

#: One candidate per this many seconds of play. Selection then trims the list
#: down to the best 10–20, so this only has to be generous, not accurate.
SECONDS_PER_CANDIDATE = 25.0
MAX_CANDIDATES = 60

_TYPES = (
    (HighlightType.GOAL_AREA_ACTION, 0.30),
    (HighlightType.HIGH_INTENSITY, 0.30),
    (HighlightType.TEAM_BUILDUP, 0.22),
    (HighlightType.CELEBRATION, 0.18),
)


class MockHighlightDetector(HighlightDetector):
    name = "mock-v1"

    def detect(self, request: DetectionRequest) -> list[Candidate]:
        duration = max(1.0, request.duration)
        rng = random.Random(f"matchly:{request.video_id}")

        wanted = min(MAX_CANDIDATES, max(3, round(duration / SECONDS_PER_CANDIDATE)))

        # Keep candidates clear of the very start and end, where a clip window
        # would be clipped to almost nothing.
        margin = min(10.0, duration * 0.05)
        span = max(1.0, duration - 2 * margin)

        candidates: list[Candidate] = []
        for index in range(wanted):
            timestamp = round(margin + span * (index + rng.random()) / wanted, 2)
            if timestamp >= duration:
                continue
            motion = round(rng.uniform(0.45, 0.98), 2)
            density = round(min(0.99, max(0.1, motion + rng.uniform(-0.12, 0.06))), 2)
            audio = round(min(0.99, max(0.05, motion - rng.uniform(0.05, 0.3))), 2)

            signals = {"motion": motion, "player_density": density}
            if request.has_audio:
                signals["audio_peak"] = audio

            score = round(sum(signals.values()) / len(signals), 2)
            candidates.append(
                Candidate(
                    timestamp=timestamp,
                    score=min(0.99, score),
                    signals=signals,
                    type=_weighted_type(rng),
                )
            )
        return candidates


def _weighted_type(rng: random.Random) -> HighlightType:
    roll = rng.random()
    cumulative = 0.0
    for kind, weight in _TYPES:
        cumulative += weight
        if roll <= cumulative:
            return kind
    return HighlightType.GENERIC
