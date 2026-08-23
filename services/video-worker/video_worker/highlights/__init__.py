"""Detector implementations available to the media worker.

The contract itself lives in :mod:`matchly_shared.highlights`; only the
implementations are here.
"""

from matchly_shared.highlights import (
    Candidate,
    ClipWindow,
    DetectionRequest,
    HighlightDetector,
    select,
    to_window,
)

from .mock import MockHighlightDetector
from .motion import MotionHighlightDetector

__all__ = [
    "Candidate",
    "ClipWindow",
    "DetectionRequest",
    "HighlightDetector",
    "MockHighlightDetector",
    "MotionHighlightDetector",
    "select",
    "to_window",
]
