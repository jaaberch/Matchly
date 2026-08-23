"""Highlight detection: the contract, the selection rules, and the MVP detector."""

from .base import Candidate, DetectionRequest, HighlightDetector
from .mock import MockHighlightDetector
from .selection import ClipWindow, select, to_window

__all__ = [
    "Candidate",
    "ClipWindow",
    "DetectionRequest",
    "HighlightDetector",
    "MockHighlightDetector",
    "select",
    "to_window",
]


def build_detector(name: str = "mock") -> HighlightDetector:
    """Detector selection.

    One place decides which implementation is live, so Phase 5's heuristic
    detector arrives as a new branch here and a config value — not as edits
    scattered through the pipeline.
    """
    if name in ("mock", "mock-v1"):
        return MockHighlightDetector()
    raise ValueError(f"Unknown highlight detector: {name!r}")
