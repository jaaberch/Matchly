"""Turning candidates into clips.

Two jobs, both independent of how candidates were found, so they are shared by
every detector: suppress overlapping moments, and expand what survives into clip
windows.
"""

from __future__ import annotations

import dataclasses

from matchly_shared.config import Settings

from .base import Candidate


@dataclasses.dataclass(frozen=True, slots=True)
class ClipWindow:
    start: float
    end: float
    candidate: Candidate

    @property
    def duration(self) -> float:
        return self.end - self.start


def _overlap_fraction(a: ClipWindow, b: ClipWindow) -> float:
    """Intersection over the shorter window, so a long clip cannot hide a short one."""
    overlap = min(a.end, b.end) - max(a.start, b.start)
    if overlap <= 0:
        return 0.0
    shortest = min(a.duration, b.duration)
    return overlap / shortest if shortest > 0 else 0.0


def to_window(candidate: Candidate, *, duration: float, settings: Settings) -> ClipWindow:
    """Expand a moment into a clip, clamped to the recording.

    A goal is worth watching from the build-up, so the window opens before the
    detected moment and closes after the celebration.
    """
    start = max(0.0, candidate.timestamp - settings.highlight_pre_roll_seconds)
    end = min(duration, candidate.timestamp + settings.highlight_post_roll_seconds)
    if end <= start:  # a candidate right at the end of a short recording
        end = min(duration, start + 1.0)
    return ClipWindow(start=round(start, 3), end=round(end, 3), candidate=candidate)


def select(candidates: list[Candidate], *, duration: float, settings: Settings) -> list[ClipWindow]:
    """Best moments, without near-duplicates.

    Temporal non-maximum suppression: walk candidates best-first and drop any
    that overlaps an already-kept clip too heavily. Without this a single burst
    of action becomes eight nearly identical clips and the reel is unwatchable.
    """
    ranked = sorted(
        (c for c in candidates if c.score >= settings.highlight_min_score),
        key=lambda c: c.score,
        reverse=True,
    )

    kept: list[ClipWindow] = []
    for candidate in ranked:
        if len(kept) >= settings.highlight_max_count:
            break
        window = to_window(candidate, duration=duration, settings=settings)
        if any(
            _overlap_fraction(window, existing) > settings.highlight_overlap_threshold
            for existing in kept
        ):
            continue
        kept.append(window)

    # Play them back in match order, not in score order.
    return sorted(kept, key=lambda window: window.start)
