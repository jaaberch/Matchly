"""Turning candidate moments into clip windows."""

from __future__ import annotations

import pytest

from matchly_shared.config import Settings
from matchly_shared.domain import HighlightType
from matchly_shared.highlights import Candidate, select, to_window


@pytest.fixture
def hl_settings() -> Settings:
    return Settings(
        highlight_pre_roll_seconds=8,
        highlight_post_roll_seconds=10,
        highlight_min_count=10,
        highlight_max_count=20,
        highlight_overlap_threshold=0.5,
        highlight_min_score=0.35,
    )


def _candidate(timestamp: float, score: float = 0.8) -> Candidate:
    return Candidate(timestamp=timestamp, score=score, signals={"motion": score})


# ── Windows ──────────────────────────────────────────────────────────────
def test_a_candidate_becomes_a_clip_around_the_moment(hl_settings: Settings) -> None:
    # The brief's example: a moment at 14:25 becomes 14:17 → 14:35.
    window = to_window(_candidate(865), duration=3600, settings=hl_settings)

    assert (window.start, window.end) == (857.0, 875.0)
    assert window.duration == 18.0


def test_a_window_is_clamped_to_the_recording(hl_settings: Settings) -> None:
    start_of_match = to_window(_candidate(2), duration=600, settings=hl_settings)
    end_of_match = to_window(_candidate(598), duration=600, settings=hl_settings)

    assert start_of_match.start == 0.0
    assert end_of_match.end == 600.0


def test_a_candidate_at_the_very_end_still_yields_a_clip(hl_settings: Settings) -> None:
    window = to_window(_candidate(600), duration=600, settings=hl_settings)
    assert window.duration > 0


# ── Selection ────────────────────────────────────────────────────────────
def test_overlapping_moments_collapse_to_the_best_one(hl_settings: Settings) -> None:
    # A single burst of action would otherwise become several near-identical
    # clips, which makes the reel unwatchable.
    windows = select(
        [_candidate(100, 0.9), _candidate(102, 0.7), _candidate(104, 0.6)],
        duration=600,
        settings=hl_settings,
    )

    assert len(windows) == 1
    assert windows[0].candidate.score == 0.9


def test_well_separated_moments_all_survive(hl_settings: Settings) -> None:
    windows = select(
        [_candidate(100), _candidate(200), _candidate(300)], duration=600, settings=hl_settings
    )
    assert len(windows) == 3


def test_low_scoring_candidates_are_dropped(hl_settings: Settings) -> None:
    windows = select(
        [_candidate(100, 0.9), _candidate(300, 0.2)], duration=600, settings=hl_settings
    )
    assert [w.candidate.score for w in windows] == [0.9]


def test_the_cap_is_respected(hl_settings: Settings) -> None:
    # 60 candidates, 40 seconds apart across an hour.
    candidates = [_candidate(60 + index * 40, 0.9) for index in range(60)]
    windows = select(candidates, duration=3600, settings=hl_settings)

    assert len(windows) == hl_settings.highlight_max_count


def test_a_real_match_yields_between_ten_and_twenty(hl_settings: Settings) -> None:
    candidates = [_candidate(30 + index * 25, 0.4 + (index % 6) / 10) for index in range(140)]
    windows = select(candidates, duration=3600, settings=hl_settings)

    assert hl_settings.highlight_min_count <= len(windows) <= hl_settings.highlight_max_count


def test_clips_come_back_in_match_order_not_score_order(hl_settings: Settings) -> None:
    windows = select(
        [_candidate(300, 0.6), _candidate(100, 0.95), _candidate(200, 0.8)],
        duration=600,
        settings=hl_settings,
    )

    assert [w.start for w in windows] == sorted(w.start for w in windows)


def test_no_candidates_yields_nothing(hl_settings: Settings) -> None:
    assert select([], duration=3600, settings=hl_settings) == []


def test_overlap_is_measured_against_the_shorter_clip(hl_settings: Settings) -> None:
    # A clip squeezed against the start of the match is short; a long one must
    # not be able to hide it just by being long.
    windows = select([_candidate(2, 0.9), _candidate(9, 0.85)], duration=600, settings=hl_settings)
    assert len(windows) == 1


# ── Candidate validation ─────────────────────────────────────────────────
@pytest.mark.parametrize("score", [-0.1, 1.5])
def test_scores_outside_zero_to_one_are_rejected(score: float) -> None:
    with pytest.raises(ValueError, match="score"):
        Candidate(timestamp=10, score=score, signals={})


def test_negative_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="timestamp"):
        Candidate(timestamp=-1, score=0.5, signals={})


def test_a_candidate_carries_its_type() -> None:
    candidate = Candidate(timestamp=10, score=0.5, signals={}, type=HighlightType.GOAL_AREA_ACTION)
    assert candidate.type is HighlightType.GOAL_AREA_ACTION
