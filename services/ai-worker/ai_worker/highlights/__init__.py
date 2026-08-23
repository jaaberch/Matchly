"""Track-based highlight scoring."""

from .heuristic import HeuristicHighlightDetector
from .signals import SignalContext, compute_signals, fuse, registered_signals

__all__ = [
    "HeuristicHighlightDetector",
    "SignalContext",
    "compute_signals",
    "fuse",
    "registered_signals",
]
