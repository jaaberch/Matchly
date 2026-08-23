"""The highlight detection contract.

Detection is the part of this product most likely to be replaced — first with
heuristics, later with a trained football-event model. So it sits behind one
small interface: a detector receives a description of the recording and returns
scored candidate moments. It does not cut clips, touch the database, or know what
a highlight row looks like.

Swapping the whole approach later means implementing :meth:`HighlightDetector.detect`.
Nothing else in the pipeline changes.

The contract lives in the shared package rather than in a worker because both
workers implement it: the media worker ships a motion-only detector that always
works, and the CV worker ships one that reads player tracks. Neither imports the
other.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..domain import HighlightType


@dataclasses.dataclass(frozen=True, slots=True)
class TrackSample:
    """One player's position at one moment, as produced by the tracking step."""

    track_ref: str
    timestamp: float
    #: Normalised 0..1 centre, so a detector never has to know the frame size.
    x: float
    y: float
    width: float
    height: float


@dataclasses.dataclass(frozen=True, slots=True)
class DetectionRequest:
    """What a detector gets to work with.

    Everything beyond ``duration`` is optional. A detector must produce something
    sensible from whatever is present, because the CV steps that fill these in
    are allowed to be missing.
    """

    video_id: str
    duration: float
    #: Low-resolution copy of the match, on local disk.
    proxy_path: Path | None = None
    #: Sampled frames, if they were extracted. Empty when they were not.
    frames: list[Path] = dataclasses.field(default_factory=list)
    frame_fps: float = 2.0
    has_audio: bool = False
    #: Player positions over time. Empty unless detection and tracking ran.
    tracks: list[TrackSample] = dataclasses.field(default_factory=list)
    #: Frame dimensions of the proxy, when known.
    frame_width: int | None = None
    frame_height: int | None = None

    @property
    def has_tracks(self) -> bool:
        return bool(self.tracks)


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
