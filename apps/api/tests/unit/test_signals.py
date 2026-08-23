"""Highlight signals and their fusion."""

from __future__ import annotations

import pytest

from ai_worker.highlights.signals import (
    SignalContext,
    compute_signals,
    fuse,
    registered_signals,
)
from matchly_shared.config import Settings
from matchly_shared.highlights import TrackSample


def walk(
    ref: str,
    *,
    start: float,
    seconds: float,
    x0: float,
    x1: float,
    y: float = 0.5,
    step: float = 0.5,
) -> list[TrackSample]:
    """A player moving in a straight line."""
    samples = []
    count = max(2, int(seconds / step))
    for index in range(count):
        progress = index / (count - 1)
        samples.append(
            TrackSample(
                track_ref=ref,
                timestamp=start + index * step,
                x=x0 + (x1 - x0) * progress,
                y=y,
                width=0.03,
                height=0.08,
            )
        )
    return samples


def test_every_signal_is_registered() -> None:
    assert set(registered_signals()) == {
        "motion",
        "acceleration",
        "player_density",
        "direction_change",
        "clustering",
        "audio_peak",
    }


# ── Individual signals ───────────────────────────────────────────────────
def test_motion_is_higher_where_players_move_faster() -> None:
    # Slow for 10s, then a sprint.
    tracks = walk("a", start=0, seconds=10, x0=0.4, x1=0.45)
    tracks += walk("a", start=10, seconds=10, x0=0.45, x1=0.95)

    computed = compute_signals(SignalContext(tracks=tracks, duration=20, has_audio=False))
    motion = computed["motion"]

    early = max(value for bucket, value in motion.items() if bucket < 9)
    late = max(value for bucket, value in motion.items() if bucket > 10)
    assert late > early


def test_player_density_peaks_near_a_goal() -> None:
    # Everyone loitering mid-pitch, then piling into the left goal area.
    tracks = [
        TrackSample(f"p{i}", timestamp=1.0, x=0.5, y=0.5, width=0.03, height=0.08) for i in range(8)
    ]
    tracks += [
        TrackSample(f"p{i}", timestamp=12.0, x=0.08, y=0.5, width=0.03, height=0.08)
        for i in range(8)
    ]

    density = compute_signals(SignalContext(tracks=tracks, duration=20, has_audio=False))[
        "player_density"
    ]

    assert density.get(12, 0) > density.get(1, 0)


def test_clustering_peaks_when_players_converge() -> None:
    spread = [
        TrackSample(
            f"p{i}", timestamp=1.0, x=0.1 + i * 0.1, y=0.2 + i * 0.08, width=0.03, height=0.08
        )
        for i in range(8)
    ]
    huddle = [
        TrackSample(
            f"p{i}", timestamp=12.0, x=0.5 + i * 0.005, y=0.5 + i * 0.005, width=0.03, height=0.08
        )
        for i in range(8)
    ]

    clustering = compute_signals(
        SignalContext(tracks=spread + huddle, duration=20, has_audio=False)
    )["clustering"]

    assert clustering.get(12, 0) > clustering.get(1, 0)


def test_clustering_ignores_a_near_empty_pitch() -> None:
    # Two players standing together is not a celebration.
    tracks = [
        TrackSample(f"p{i}", timestamp=1.0, x=0.5, y=0.5, width=0.03, height=0.08) for i in range(2)
    ]

    computed = compute_signals(SignalContext(tracks=tracks, duration=10, has_audio=False))

    assert "clustering" not in computed


def test_audio_is_absent_without_a_microphone() -> None:
    tracks = walk("a", start=0, seconds=10, x0=0.1, x1=0.9)

    computed = compute_signals(SignalContext(tracks=tracks, duration=10, has_audio=False))

    assert "audio_peak" not in computed


def test_no_tracks_yields_no_signals() -> None:
    assert compute_signals(SignalContext(tracks=[], duration=60, has_audio=False)) == {}


# ── Fusion ───────────────────────────────────────────────────────────────
@pytest.fixture
def weights() -> dict[str, float]:
    return Settings().signal_weights


def test_fusion_scores_stay_in_range(weights) -> None:
    tracks = walk("a", start=0, seconds=20, x0=0.1, x1=0.9)
    computed = compute_signals(SignalContext(tracks=tracks, duration=20, has_audio=False))

    fused = fuse(computed, weights, buckets=20)

    assert fused
    assert all(0.0 <= score <= 1.0 for _, score, _ in fused)
    assert all(timestamp >= 0 for timestamp, _, _ in fused)


def test_weights_renormalise_over_the_signals_that_exist(weights) -> None:
    """A silent camera must not cap every score.

    The configured weights sum to 1 across six signals. With audio missing they
    would only ever sum to 0.9, quietly depressing every score in the match — so
    fusion renormalises over what it was actually given.
    """
    tracks = walk("a", start=0, seconds=20, x0=0.1, x1=0.9)
    computed = compute_signals(SignalContext(tracks=tracks, duration=20, has_audio=False))

    fused = fuse(computed, weights, buckets=20)

    assert max(score for _, score, _ in fused) > 0.5


def test_fusion_reports_which_signals_contributed(weights) -> None:
    tracks = walk("a", start=0, seconds=20, x0=0.1, x1=0.9)
    computed = compute_signals(SignalContext(tracks=tracks, duration=20, has_audio=False))

    fused = fuse(computed, weights, buckets=20)

    contributions = fused[0][2]
    assert contributions
    assert set(contributions) <= set(computed)


def test_fusion_with_no_signals_produces_nothing(weights) -> None:
    assert fuse({}, weights, buckets=20) == []


def test_zero_weights_produce_nothing() -> None:
    tracks = walk("a", start=0, seconds=10, x0=0.1, x1=0.9)
    computed = compute_signals(SignalContext(tracks=tracks, duration=10, has_audio=False))

    assert fuse(computed, dict.fromkeys(computed, 0.0), buckets=10) == []
