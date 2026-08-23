"""Temporal voting: turning many unreliable reads into one usable answer.

A jersey number read from a single frame is worthless. The player is turning, the
number is creased, another player is in the way, the shot is wide. Any of those
produces a confident wrong answer.

So no single frame is trusted. Reads are accumulated across a track and combined
by confidence, and the result is only accepted if it clears three bars: enough
votes, a clear enough winner, and enough total confidence behind it. Below any of
those the track stays unattributed — which is a perfectly good outcome, because
an unattributed highlight is a general match highlight, while a *wrongly*
attributed one puts another player's goal in your feed.

Worked example, from the brief::

    frame 1020 -> #7  conf .62
    frame 1030 -> #7  conf .81
    frame 1040 -> #1  conf .32     <- outlier, outvoted
    frame 1050 -> #7  conf .78

    #7 with confidence 0.82

The confidence reported is the winner's share of all confidence cast, so a track
that saw #7 four times and #1 once is more certain than one that saw each twice.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Iterable

#: A number needs at least this many reads before it can win anything.
MIN_VOTES = 3
#: The winner must hold at least this share of the confidence cast.
MIN_SHARE = 0.5
#: …and beat the runner-up by at least this much of it. Two numbers at 45/40 is
#: a coin toss, not a reading.
MIN_MARGIN = 0.15
#: Reads below this are ignored entirely rather than diluting the vote.
MIN_READ_CONFIDENCE = 0.2


@dataclasses.dataclass(frozen=True, slots=True)
class JerseyRead:
    """One recognizer output for one frame."""

    number: int
    confidence: float
    timestamp: float = 0.0


@dataclasses.dataclass(frozen=True, slots=True)
class JerseyVerdict:
    """What a whole track decided, and the evidence for it."""

    number: int | None
    confidence: float
    votes: int
    total_reads: int
    #: Per-number confidence share, for auditing a bad attribution later.
    distribution: dict[int, float] = dataclasses.field(default_factory=dict)
    rejection: str | None = None

    @property
    def attributed(self) -> bool:
        return self.number is not None


def vote(
    reads: Iterable[JerseyRead],
    *,
    allowed_numbers: set[int] | None = None,
    min_votes: int = MIN_VOTES,
    min_share: float = MIN_SHARE,
    min_margin: float = MIN_MARGIN,
    min_read_confidence: float = MIN_READ_CONFIDENCE,
) -> JerseyVerdict:
    """Combine a track's reads into one verdict.

    ``allowed_numbers`` constrains the answer to numbers actually registered at
    check-in. This matters more than any model improvement: it turns a 100-way
    classification into a choice among the dozen numbers on the pitch, and a read
    of "38" when nobody wears 38 is discarded instead of inventing a player.
    """
    reads = list(reads)
    total_reads = len(reads)

    usable = [
        read
        for read in reads
        if read.confidence >= min_read_confidence
        and (allowed_numbers is None or read.number in allowed_numbers)
    ]
    if not usable:
        return JerseyVerdict(
            number=None,
            confidence=0.0,
            votes=0,
            total_reads=total_reads,
            rejection="no usable reads",
        )

    weights: dict[int, float] = defaultdict(float)
    counts: dict[int, int] = defaultdict(int)
    for read in usable:
        weights[read.number] += read.confidence
        counts[read.number] += 1

    total_weight = sum(weights.values())
    distribution = {number: round(weight / total_weight, 3) for number, weight in weights.items()}

    ranked = sorted(weights.items(), key=lambda item: item[1], reverse=True)
    winner, winner_weight = ranked[0]
    runner_up_weight = ranked[1][1] if len(ranked) > 1 else 0.0

    share = winner_weight / total_weight
    margin = (winner_weight - runner_up_weight) / total_weight

    if counts[winner] < min_votes:
        rejection = f"only {counts[winner]} reads of #{winner}, need {min_votes}"
    elif share < min_share:
        rejection = f"#{winner} holds {share:.0%} of confidence, need {min_share:.0%}"
    elif margin < min_margin:
        rejection = f"#{winner} leads by {margin:.0%}, need {min_margin:.0%}"
    else:
        rejection = None

    if rejection is not None:
        return JerseyVerdict(
            number=None,
            confidence=round(share, 3),
            votes=counts[winner],
            total_reads=total_reads,
            distribution=distribution,
            rejection=rejection,
        )

    return JerseyVerdict(
        number=winner,
        confidence=round(share, 3),
        votes=counts[winner],
        total_reads=total_reads,
        distribution=distribution,
    )
