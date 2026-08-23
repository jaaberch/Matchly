"""Guards against tests quietly disappearing.

The video and computer-vision suites skip themselves when their runtime is
absent, which is right on a laptop and dangerous in CI: a missing ffmpeg would
turn the most valuable tests in the project into a green tick over nothing.

So the skips are conditional on the environment declaring what it has. CI says
so, and these fail the build when the declaration is not true.
"""

from __future__ import annotations

import os

import pytest

from video_worker import ffmpeg

IN_CI = os.environ.get("CI", "").lower() in ("1", "true", "yes")
CV_REQUIRED = os.environ.get("MATCHLY_REQUIRE_CV", "").lower() in ("1", "true", "yes")


@pytest.mark.skipif(not IN_CI, reason="only enforced in CI")
def test_ci_has_ffmpeg() -> None:
    """Without ffmpeg the pipeline tests skip and CI proves nothing."""
    assert ffmpeg.available(), (
        "ffmpeg and ffprobe must be installed in CI. Without them the video "
        "pipeline tests skip silently and the build is green over nothing."
    )


@pytest.mark.skipif(not CV_REQUIRED, reason="MATCHLY_REQUIRE_CV is not set")
def test_the_cv_runtime_is_present_when_declared() -> None:
    """The CV job installs the extras; if the import fails, say so loudly."""
    from ai_worker.detection import available

    assert available("yolov8n.pt"), (
        "MATCHLY_REQUIRE_CV is set but the detection model could not be loaded. "
        "Either the CV extras are not installed or the weights could not be "
        "fetched — in both cases the CV tests would skip and prove nothing."
    )


@pytest.mark.skipif(not CV_REQUIRED, reason="MATCHLY_REQUIRE_CV is not set")
def test_the_full_detector_ladder_is_available_when_cv_is() -> None:
    """All three rungs, in a deployment that has everything."""
    import ai_worker.steps  # noqa: F401
    import video_worker.steps  # noqa: F401
    from matchly_shared.highlights import registered_detectors

    assert set(registered_detectors()) == {"mock", "motion", "heuristic"}


def test_the_media_worker_always_has_a_detector() -> None:
    """True in every deployment, so this one is never skipped.

    If it fails, some refactor has emptied the ladder and every match would fail
    at SCORE_EVENTS — which is exactly how that happened once already.
    """
    import video_worker.steps  # noqa: F401
    from matchly_shared.highlights import DetectionRequest, build_detector

    assert build_detector(DetectionRequest(video_id="v", duration=60.0)).name
