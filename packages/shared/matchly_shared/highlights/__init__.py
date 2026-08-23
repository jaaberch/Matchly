"""Highlight detection: the contract, and the rules for turning moments into clips.

Detector *implementations* live in the workers — a motion-only one that always
works, and a computer-vision one that reads player tracks. Both satisfy the same
protocol, so the pipeline never knows which it has.
"""

from .base import Candidate, DetectionRequest, HighlightDetector, TrackSample
from .registry import (
    build_detector,
    clear_registry,
    register_detector,
    registered_detectors,
)
from .selection import ClipWindow, select, to_window

__all__ = [
    "Candidate",
    "ClipWindow",
    "DetectionRequest",
    "HighlightDetector",
    "TrackSample",
    "build_detector",
    "clear_registry",
    "register_detector",
    "registered_detectors",
    "select",
    "to_window",
]
