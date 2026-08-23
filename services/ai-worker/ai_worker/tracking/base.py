"""What a tracker is: detections in, tracks out."""

from __future__ import annotations

import dataclasses
from typing import Protocol, runtime_checkable

from ..detection import Box, FrameDetections


@dataclasses.dataclass(slots=True)
class TrackPoint:
    frame_index: int
    timestamp: float
    box: Box


@dataclasses.dataclass(slots=True)
class Track:
    """One player followed across frames.

    ``ref`` is stable only within a video. Tracks break and restart when players
    occlude each other, which is exactly why jersey attribution votes across a
    track rather than trusting any single frame.
    """

    ref: str
    points: list[TrackPoint] = dataclasses.field(default_factory=list)

    @property
    def first_seen(self) -> float:
        return self.points[0].timestamp if self.points else 0.0

    @property
    def last_seen(self) -> float:
        return self.points[-1].timestamp if self.points else 0.0

    @property
    def duration(self) -> float:
        return self.last_seen - self.first_seen

    @property
    def length(self) -> int:
        return len(self.points)

    def centres(self) -> list[tuple[float, float, float]]:
        """``(timestamp, x, y)`` for each point — the input to the motion signals."""
        return [(point.timestamp, *point.box.centre) for point in self.points]


@runtime_checkable
class Tracker(Protocol):
    name: str

    def track(self, frames: list[FrameDetections]) -> list[Track]: ...
