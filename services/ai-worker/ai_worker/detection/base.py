"""What a player detector is.

One method, one shape. The pipeline never names an implementation, so replacing
YOLO with a football-specific model — or a hosted inference endpoint — is a new
class and a config value.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclasses.dataclass(frozen=True, slots=True)
class Box:
    """An axis-aligned box in pixels, plus how sure the detector is."""

    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    def iou(self, other: Box) -> float:
        """Intersection over union — the association metric the tracker uses."""
        left, top = max(self.x1, other.x1), max(self.y1, other.y1)
        right, bottom = min(self.x2, other.x2), min(self.y2, other.y2)
        if right <= left or bottom <= top:
            return 0.0
        overlap = (right - left) * (bottom - top)
        union = self.area + other.area - overlap
        return overlap / union if union > 0 else 0.0

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)


@dataclasses.dataclass(frozen=True, slots=True)
class FrameDetections:
    """Everything found in one sampled frame."""

    frame_index: int
    timestamp: float
    boxes: list[Box]

    @property
    def count(self) -> int:
        return len(self.boxes)


@runtime_checkable
class PlayerDetector(Protocol):
    """Finds people in frames."""

    name: str

    def detect(self, frames: list[Path], *, fps: float) -> list[FrameDetections]:
        """Detections for each frame, in frame order.

        ``fps`` is the sampling rate, used to turn a frame index into a
        timestamp in the recording.
        """
        ...
