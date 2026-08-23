"""The highlight detection contract.

Detection is the part of this product most likely to be replaced — first with
heuristics, later with a trained football-event model. So it sits behind one
small interface: a detector receives a description of the recording and returns
scored candidate moments. It does not cut clips, touch the database, or know what
a highlight row looks like.

Swapping the whole approach later means implementing :meth:`HighlightDetector.detect`.
Nothing else in the pipeline changes.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Protocol, runtime_checkable

from matchly_shared.domain import HighlightType


@dataclasses.dataclass(frozen=True, slots=True)
class DetectionRequest:
    """What a detector gets to work with."""

    video_id: str
    duration: float
    #: Low-resolution copy of the match, on local disk.
    proxy_path: Path | None
    #: Sampled frames, if SAMPLE_FRAMES ran. Empty when it was skipped.
    frames: list[Path]
    frame_fps: float
    has_audio: bool


@dataclasses.dataclass(frozen=True, slots=True)
class Candidate:
    """One scored moment.

    ``timestamp`` is the centre of the action, not the start of the clip; the
    pre-roll and post-roll are applied afterwards so the same candidate can be
    cut into different clip lengths without re-detecting.
    """

    timestamp: float
    score: float
    signals: dict[str, float]
    type: HighlightType = HighlightType.GENERIC

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be within 0..1, got {self.score}")
        if self.timestamp < 0:
            raise ValueError("timestamp cannot be negative")


@runtime_checkable
class HighlightDetector(Protocol):
    """Produces candidate moments for a recording."""

    #: Recorded on each highlight so a match's clips can be traced to the
    #: detector that made them — which matters the day the model changes.
    name: str

    def detect(self, request: DetectionRequest) -> list[Candidate]: ...
