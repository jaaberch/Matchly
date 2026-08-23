"""Detector selection.

Detectors register themselves with a priority and a predicate saying what data
they need. The pipeline then asks for the best one the *available* data supports,
rather than naming an implementation.

That is what makes the fallback structural instead of a convention. A worker
without the computer-vision dependencies never registers the CV detector, so the
motion-only one is simply the best available and the match still gets highlights.
Nothing has to catch an ImportError or check a feature flag.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from ..logging import get_logger
from .base import DetectionRequest, HighlightDetector

logger = get_logger(__name__)

DetectorFactory = Callable[[], HighlightDetector]
Predicate = Callable[[DetectionRequest], bool]


@dataclasses.dataclass(frozen=True, slots=True)
class _Registration:
    name: str
    priority: int
    factory: DetectorFactory
    supports: Predicate


_REGISTRY: dict[str, _Registration] = {}


def register_detector(
    name: str,
    *,
    priority: int,
    supports: Predicate = lambda request: True,
) -> Callable[[DetectorFactory], DetectorFactory]:
    """Register a detector factory.

    ``priority`` orders candidates: the highest one whose ``supports`` predicate
    accepts the request wins. A universal fallback registers at priority 0 with
    the default predicate.
    """

    def decorator(factory: DetectorFactory) -> DetectorFactory:
        _REGISTRY[name] = _Registration(
            name=name, priority=priority, factory=factory, supports=supports
        )
        return factory

    return decorator


def build_detector(request: DetectionRequest) -> HighlightDetector:
    """The best detector this process can offer for this recording."""
    candidates = sorted(_REGISTRY.values(), key=lambda item: item.priority, reverse=True)
    for candidate in candidates:
        if candidate.supports(request):
            logger.info(
                "highlights.detector_selected",
                extra={
                    "detector": candidate.name,
                    "has_tracks": request.has_tracks,
                    "considered": len(candidates),
                },
            )
            return candidate.factory()
    raise RuntimeError(
        "No highlight detector is registered. The media worker must import its "
        "detector module; without one a match can never produce highlights."
    )


def registered_detectors() -> dict[str, int]:
    """Name to priority, for diagnostics and the admin dashboard."""
    return {item.name: item.priority for item in _REGISTRY.values()}


def clear_registry() -> None:
    """Test helper."""
    _REGISTRY.clear()
