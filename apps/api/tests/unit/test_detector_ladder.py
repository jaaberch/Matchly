"""The detector ladder.

"Every AI component has a fallback" is expressed here structurally rather than by
convention: detectors declare what data they need, and the pipeline asks for the
best one the available data supports. Nothing catches an ImportError or reads a
feature flag.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from matchly_shared.highlights import (
    Candidate,
    DetectionRequest,
    TrackSample,
    build_detector,
    register_detector,
    registered_detectors,
)
from matchly_shared.highlights import registry as registry_module


@pytest.fixture
def ladder() -> Iterator[None]:
    """Swap the registry, so the real workers' detectors do not interfere."""
    saved = dict(registry_module._REGISTRY)
    registry_module._REGISTRY.clear()
    yield
    registry_module._REGISTRY.clear()
    registry_module._REGISTRY.update(saved)


class _Stub:
    def __init__(self, name: str) -> None:
        self.name = name

    def detect(self, request: DetectionRequest) -> list[Candidate]:
        return []


def _register(name: str, priority: int, supports=lambda request: True) -> None:
    register_detector(name, priority=priority, supports=supports)(lambda: _Stub(name))


def _request(**kwargs) -> DetectionRequest:
    return DetectionRequest(video_id="v", duration=60.0, **kwargs)


# ── Selection ────────────────────────────────────────────────────────────
def test_the_highest_priority_supported_detector_wins(ladder) -> None:
    _register("floor", 0)
    _register("best", 100)

    assert build_detector(_request()).name == "best"


def test_an_unsupported_detector_is_passed_over(ladder) -> None:
    _register("floor", 0)
    _register("needs_tracks", 100, supports=lambda request: request.has_tracks)

    assert build_detector(_request()).name == "floor"


def test_it_takes_the_better_one_once_its_data_exists(ladder) -> None:
    _register("floor", 0)
    _register("needs_tracks", 100, supports=lambda request: request.has_tracks)

    with_tracks = _request(tracks=[TrackSample("t1", 1.0, 0.5, 0.5, 0.1, 0.2)])

    assert build_detector(with_tracks).name == "needs_tracks"


def test_the_full_ladder_degrades_step_by_step(ladder) -> None:
    _register("mock", 0)
    _register("motion", 50, supports=lambda request: request.proxy_path is not None)
    _register("heuristic", 100, supports=lambda request: request.has_tracks)

    nothing = _request()
    pixels = _request(proxy_path=Path("/tmp/proxy.mp4"))
    tracks = _request(
        proxy_path=Path("/tmp/proxy.mp4"),
        tracks=[TrackSample("t1", 1.0, 0.5, 0.5, 0.1, 0.2)],
    )

    assert build_detector(nothing).name == "mock"
    assert build_detector(pixels).name == "motion"
    assert build_detector(tracks).name == "heuristic"


def test_an_empty_ladder_is_a_loud_failure(ladder) -> None:
    # Silence here would mean a match with no highlights and no explanation.
    with pytest.raises(RuntimeError, match="No highlight detector"):
        build_detector(_request())


def test_registering_the_same_name_twice_replaces_it(ladder) -> None:
    _register("thing", 0)
    _register("thing", 100)

    assert registered_detectors() == {"thing": 100}


# ── The real ladder, as the workers assemble it ──────────────────────────
def test_the_media_worker_can_always_score_something() -> None:
    """A worker with no computer vision must still deliver highlights."""
    import video_worker.steps  # noqa: F401  (registers its detectors)

    detector = build_detector(DetectionRequest(video_id="v", duration=60.0))

    assert detector.name  # not an exception
    assert detector.detect(DetectionRequest(video_id="v", duration=60.0)) is not None


def test_the_media_worker_prefers_pixels_to_guessing(tmp_path) -> None:
    import video_worker.steps  # noqa: F401

    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(b"not really a video")

    detector = build_detector(DetectionRequest(video_id="v", duration=60.0, proxy_path=proxy))

    assert detector.name == "motion-v1"
