"""ByteTrack association, without the dependency.

ByteTrack's insight is that low-confidence detections are usually *occluded
players*, not noise. Most trackers discard them and lose the track; ByteTrack
matches high-confidence boxes first, then gives the surviving tracks a second
chance against the leftovers. On a wide pitch shot, where players constantly pass
in front of one another, that difference is most of the tracking quality.

Implemented here rather than pulled in because the useful part is the two-stage
association — perhaps eighty lines — while the packages that provide it bring
their own tensor stacks. A constant-velocity predictor stands in for the Kalman
filter: at 2 fps on a fixed camera, positional prediction contributes little and
costs a dependency.

Replaceable like everything else: implement :class:`Tracker`.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from matchly_shared.logging import get_logger

from ..detection import Box, FrameDetections
from .base import Track, Tracker, TrackPoint

logger = get_logger(__name__)

#: Detections above this join a track directly; below it they only rescue one.
HIGH_CONFIDENCE = 0.5
#: Below this a detection is discarded entirely.
LOW_CONFIDENCE = 0.1
#: Minimum overlap to call two boxes the same player.
MATCH_IOU = 0.3
#: A rescued match is allowed to be looser: the player is partly hidden.
RESCUE_IOU = 0.2
#: Frames a track may go unseen before it is closed.
MAX_AGE = 6
#: Tracks shorter than this are noise — a shadow, a spectator, a line marking.
MIN_TRACK_LENGTH = 3


@dataclass(slots=True)
class _Candidate:
    ref: str
    box: Box
    points: list[TrackPoint] = field(default_factory=list)
    misses: int = 0
    velocity: tuple[float, float] = (0.0, 0.0)

    def predict(self) -> Box:
        """Where this player probably is now, assuming they kept going."""
        dx, dy = self.velocity
        return Box(
            x1=self.box.x1 + dx,
            y1=self.box.y1 + dy,
            x2=self.box.x2 + dx,
            y2=self.box.y2 + dy,
            confidence=self.box.confidence,
        )

    def update(self, box: Box, point: TrackPoint) -> None:
        previous_x, previous_y = self.box.centre
        current_x, current_y = box.centre
        # Smoothed, so one jittery frame does not fling the prediction away.
        self.velocity = (
            0.5 * self.velocity[0] + 0.5 * (current_x - previous_x),
            0.5 * self.velocity[1] + 0.5 * (current_y - previous_y),
        )
        self.box = box
        self.points.append(point)
        self.misses = 0


def _associate(
    candidates: list[_Candidate], boxes: list[Box], threshold: float
) -> tuple[list[tuple[int, int]], set[int], set[int]]:
    """Greedy IoU matching.

    Greedy rather than Hungarian: at seven-a-side densities the two agree almost
    always, and greedy is far easier to reason about when a match looks wrong.
    """
    scored = [
        (candidate.predict().iou(box), c_index, b_index)
        for c_index, candidate in enumerate(candidates)
        for b_index, box in enumerate(boxes)
    ]
    scored.sort(reverse=True)

    pairs: list[tuple[int, int]] = []
    used_candidates: set[int] = set()
    used_boxes: set[int] = set()
    for score, c_index, b_index in scored:
        if score < threshold:
            break
        if c_index in used_candidates or b_index in used_boxes:
            continue
        pairs.append((c_index, b_index))
        used_candidates.add(c_index)
        used_boxes.add(b_index)

    unmatched_candidates = set(range(len(candidates))) - used_candidates
    unmatched_boxes = set(range(len(boxes))) - used_boxes
    return pairs, unmatched_candidates, unmatched_boxes


class ByteTracker(Tracker):
    name = "bytetrack-lite"

    def __init__(
        self,
        *,
        high_confidence: float = HIGH_CONFIDENCE,
        low_confidence: float = LOW_CONFIDENCE,
        match_iou: float = MATCH_IOU,
        rescue_iou: float = RESCUE_IOU,
        max_age: int = MAX_AGE,
        min_track_length: int = MIN_TRACK_LENGTH,
    ) -> None:
        self.high_confidence = high_confidence
        self.low_confidence = low_confidence
        self.match_iou = match_iou
        self.rescue_iou = rescue_iou
        self.max_age = max_age
        self.min_track_length = min_track_length

    def track(self, frames: list[FrameDetections]) -> list[Track]:
        live: list[_Candidate] = []
        finished: list[_Candidate] = []
        refs = itertools.count(1)

        for frame in frames:
            strong = [box for box in frame.boxes if box.confidence >= self.high_confidence]
            weak = [
                box
                for box in frame.boxes
                if self.low_confidence <= box.confidence < self.high_confidence
            ]

            # Stage one: confident detections claim their tracks.
            pairs, unmatched_tracks, unmatched_strong = _associate(live, strong, self.match_iou)
            for c_index, b_index in pairs:
                box = strong[b_index]
                live[c_index].update(box, TrackPoint(frame.frame_index, frame.timestamp, box))

            # Stage two: whatever is left over rescues the tracks nothing claimed.
            # This is the part that keeps a player through an occlusion.
            leftovers = [live[index] for index in sorted(unmatched_tracks)]
            rescued, still_unmatched, _ = _associate(leftovers, weak, self.rescue_iou)
            rescued_refs = set()
            for c_index, b_index in rescued:
                candidate = leftovers[c_index]
                box = weak[b_index]
                candidate.update(box, TrackPoint(frame.frame_index, frame.timestamp, box))
                rescued_refs.add(candidate.ref)

            for candidate in leftovers:
                if candidate.ref not in rescued_refs:
                    candidate.misses += 1

            # Confident detections that matched nothing start new tracks.
            for b_index in sorted(unmatched_strong):
                box = strong[b_index]
                candidate = _Candidate(ref=f"t{next(refs)}", box=box)
                candidate.points.append(TrackPoint(frame.frame_index, frame.timestamp, box))
                live.append(candidate)

            still_live = [c for c in live if c.misses <= self.max_age]
            finished.extend(c for c in live if c.misses > self.max_age)
            live = still_live

        finished.extend(live)
        tracks = [
            Track(ref=candidate.ref, points=candidate.points)
            for candidate in finished
            if len(candidate.points) >= self.min_track_length
        ]
        tracks.sort(key=lambda track: track.first_seen)

        logger.info(
            "tracking.completed",
            extra={
                "frames": len(frames),
                "tracks": len(tracks),
                "discarded_short": len(finished) - len(tracks),
            },
        )
        return tracks
