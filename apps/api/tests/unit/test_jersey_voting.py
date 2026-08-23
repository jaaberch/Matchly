"""Temporal voting for jersey numbers.

The rule this enforces: a wrong attribution is worse than none. A highlight with
no player attached is a general match highlight; one attached to the wrong player
puts someone else's goal in your feed.
"""

from __future__ import annotations

import pytest

from ai_worker.jersey import vote
from ai_worker.jersey.voting import JerseyRead


def reads(*pairs: tuple[int, float]) -> list[JerseyRead]:
    return [
        JerseyRead(number=number, confidence=confidence, timestamp=index)
        for index, (number, confidence) in enumerate(pairs)
    ]


# ── The worked example from the brief ────────────────────────────────────
def test_an_outlier_is_outvoted() -> None:
    verdict = vote(reads((7, 0.62), (7, 0.81), (1, 0.32), (7, 0.78)))

    assert verdict.number == 7
    assert verdict.attributed
    assert verdict.votes == 3
    assert verdict.total_reads == 4
    # Confidence is the winner's share of all confidence cast.
    assert verdict.confidence == pytest.approx(0.87, abs=0.02)


def test_the_distribution_is_kept_for_auditing() -> None:
    verdict = vote(reads((7, 0.6), (7, 0.8), (1, 0.4), (7, 0.7)))

    assert set(verdict.distribution) == {7, 1}
    assert verdict.distribution[7] > verdict.distribution[1]
    assert sum(verdict.distribution.values()) == pytest.approx(1.0, abs=0.01)


# ── Refusing to answer ───────────────────────────────────────────────────
def test_a_split_vote_is_not_attributed() -> None:
    verdict = vote(reads((7, 0.5), (9, 0.5), (7, 0.5), (9, 0.5), (7, 0.5), (9, 0.5)))

    assert verdict.number is None
    assert "leads by" in verdict.rejection


def test_too_few_reads_is_not_attributed_however_confident() -> None:
    verdict = vote(reads((7, 0.99), (7, 0.99)))

    assert verdict.number is None
    assert "need 3" in verdict.rejection


def test_a_narrow_lead_is_not_attributed() -> None:
    # 55/45 is not a reading, it is a coin toss with extra steps.
    verdict = vote(reads((7, 0.9), (7, 0.9), (7, 0.9), (9, 0.85), (9, 0.85), (9, 0.8)))

    assert verdict.number is None


def test_no_reads_at_all() -> None:
    verdict = vote([])

    assert verdict.number is None
    assert verdict.total_reads == 0
    assert verdict.rejection == "no usable reads"


def test_low_confidence_reads_are_discarded_not_counted() -> None:
    # Three reads, but all too weak to mean anything.
    verdict = vote(reads((7, 0.05), (7, 0.1), (7, 0.15)))

    assert verdict.number is None


# ── Constrained matching ─────────────────────────────────────────────────
def test_a_number_nobody_wears_is_discarded() -> None:
    """The single highest-value constraint in the whole feature.

    Restricting the answer to numbers registered at check-in turns a hundred-way
    guess into a choice among the dozen on the pitch, and stops the recognizer
    inventing a player out of a misread sponsor logo.
    """
    verdict = vote(reads((38, 0.9), (38, 0.9), (38, 0.9)), allowed_numbers={7, 9, 10})

    assert verdict.number is None
    assert verdict.rejection == "no usable reads"


def test_constraining_lets_the_registered_number_win() -> None:
    # #3 is read confidently but nobody wears it; #7 wins on what remains.
    verdict = vote(
        reads((3, 0.95), (3, 0.9), (7, 0.5), (7, 0.55), (7, 0.6)),
        allowed_numbers={7, 9, 10},
    )

    assert verdict.number == 7


def test_without_constraints_anything_in_range_can_win() -> None:
    verdict = vote(reads((38, 0.9), (38, 0.9), (38, 0.9)))
    assert verdict.number == 38


# ── Thresholds are configurable ──────────────────────────────────────────
def test_thresholds_can_be_relaxed() -> None:
    sparse = reads((7, 0.9), (7, 0.9))

    assert vote(sparse).number is None
    assert vote(sparse, min_votes=2).number == 7


def test_thresholds_can_be_tightened() -> None:
    clear = reads((7, 0.9), (7, 0.9), (7, 0.9), (7, 0.9))

    assert vote(clear).number == 7
    assert vote(clear, min_votes=10).number is None


# ── Confidence semantics ─────────────────────────────────────────────────
def test_unanimity_scores_higher_than_a_contested_win() -> None:
    unanimous = vote(reads((7, 0.8), (7, 0.8), (7, 0.8), (7, 0.8)))
    contested = vote(reads((7, 0.8), (7, 0.8), (7, 0.8), (9, 0.5), (9, 0.4)))

    assert unanimous.number == contested.number == 7
    assert unanimous.confidence > contested.confidence
    assert unanimous.confidence == pytest.approx(1.0)
