"""Computer-vision step implementations.

Importing this package registers DETECT_PLAYERS, TRACK and JERSEY_OCR, and makes
the track-based highlight detector available to the ladder. A worker that does
not import it leaves those steps PENDING and scores on motion alone.
"""

from .. import highlights  # noqa: F401  (registers the heuristic detector)
from . import cv  # noqa: F401  (registers the CV steps)

__all__ = ["cv", "highlights"]
