"""Multi-object tracking.

Synthetic detections rather than real footage, so each behaviour — occlusion,
crossing, noise — is isolated and the assertion says what it is testing.
"""

from __future__ import annotations

import pytest

from ai_worker.detection import Box, FrameDetections
from ai_worker.tracking import ByteTracker


def box(x: float, y: float, w: float = 40, h: float = 80, conf: float = 0.9) -> Box:
    return Box(x1=x, y1=y, x2=x + w, y2=y + h, confidence=conf)


def frames(per_frame: list[list[Box]], fps: float = 2.0) -> list[FrameDetections]:
    return [
        FrameDetections(frame_index=index, timestamp=index / fps, boxes=boxes)
        for index, boxes in enumerate(per_frame)
    ]


# ── Box geometry ─────────────────────────────────────────────────────────
def test_iou_of_identical_boxes_is_one() -> None:
    assert box(0, 0).iou(box(0, 0)) == pytest.approx(1.0)


def test_disjoint_boxes_do_not_overlap() -> None:
    assert box(0, 0).iou(box(500, 500)) == 0.0


def test_touching_edges_do_not_count_as_overlap() -> None:
    assert box(0, 0, 40, 80).iou(box(40, 0, 40, 80)) == 0.0


def test_half_overlap() -> None:
    # Two 40x80 boxes offset by 20 share half their width.
    assert box(0, 0).iou(box(20, 0)) == pytest.approx(1 / 3, abs=0.01)


# ── Basic tracking ───────────────────────────────────────────────────────
def test_a_player_walking_across_the_frame_is_one_track() -> None:
    tracks = ByteTracker().track(frames([[box(100 + i * 5, 100)] for i in range(15)]))

    assert len(tracks) == 1
    assert tracks[0].length == 15
    assert tracks[0].duration == pytest.approx(7.0)


def test_two_players_stay_separate() -> None:
    tracks = ByteTracker().track(
        frames([[box(100 + i * 5, 100), box(500 - i * 5, 300)] for i in range(15)])
    )

    assert len(tracks) == 2
    assert all(track.length == 15 for track in tracks)


def test_a_player_arriving_late_starts_a_new_track() -> None:
    sequence = [[box(100 + i * 5, 100)] for i in range(6)]
    sequence += [[box(100 + i * 5, 100), box(400, 300)] for i in range(6, 14)]

    tracks = ByteTracker().track(frames(sequence))

    assert len(tracks) == 2
    assert sorted(track.length for track in tracks) == [8, 14]


# ── The ByteTrack behaviour that matters ─────────────────────────────────
def test_a_low_confidence_run_rescues_the_track_instead_of_breaking_it() -> None:
    """The reason ByteTrack's second stage exists.

    A player passing behind another produces weak detections. Discarding them —
    what a single-stage tracker does — ends the track and starts a new one, and
    the jersey vote then has two half-length tracks instead of one good one.
    """
    sequence = []
    for index in range(20):
        confidence = 0.3 if 8 <= index <= 12 else 0.9
        sequence.append([box(100 + index * 6, 100, conf=confidence)])

    tracks = ByteTracker().track(frames(sequence))

    assert len(tracks) == 1, "the occlusion split the track"
    assert tracks[0].length == 20


def test_detections_below_the_floor_are_ignored_entirely() -> None:
    # 0.05 is noise, not an occluded player.
    tracks = ByteTracker().track(frames([[box(100, 100, conf=0.05)] for _ in range(10)]))
    assert tracks == []


def test_weak_detections_alone_never_start_a_track() -> None:
    # A track can only be *created* by a confident detection; weak ones only
    # continue an existing one. Otherwise shadows become players.
    tracks = ByteTracker().track(frames([[box(100, 100, conf=0.3)] for _ in range(10)]))
    assert tracks == []


def test_a_brief_disappearance_is_tolerated() -> None:
    sequence = [[box(100 + i * 5, 100)] for i in range(6)]
    sequence += [[] for _ in range(3)]  # fully missed for three frames
    sequence += [[box(100 + i * 5, 100)] for i in range(9, 16)]

    tracks = ByteTracker().track(frames(sequence))

    assert len(tracks) == 1
    assert tracks[0].length == 13


def test_a_long_disappearance_closes_the_track() -> None:
    sequence = [[box(100, 100)] for _ in range(6)]
    sequence += [[] for _ in range(10)]  # gone well past max_age
    sequence += [[box(400, 300)] for _ in range(6)]

    tracks = ByteTracker().track(frames(sequence))

    assert len(tracks) == 2


# ── Noise rejection ──────────────────────────────────────────────────────
def test_a_one_frame_detection_is_not_a_track() -> None:
    assert ByteTracker().track(frames([[box(10, 10)]])) == []


def test_short_tracks_are_discarded() -> None:
    tracker = ByteTracker(min_track_length=5)
    assert tracker.track(frames([[box(10, 10)] for _ in range(3)])) == []
    assert len(tracker.track(frames([[box(10, 10)] for _ in range(6)]))) == 1


def test_no_detections_yields_no_tracks() -> None:
    assert ByteTracker().track(frames([[] for _ in range(10)])) == []
    assert ByteTracker().track([]) == []


# ── Output shape ─────────────────────────────────────────────────────────
def test_tracks_come_back_in_the_order_they_appeared() -> None:
    sequence = [[box(100, 100)] for _ in range(5)]
    sequence += [[box(100, 100), box(400, 400)] for _ in range(5)]

    tracks = ByteTracker().track(frames(sequence))

    assert [track.first_seen for track in tracks] == sorted(t.first_seen for t in tracks)


def test_centres_feed_the_motion_signals() -> None:
    tracks = ByteTracker().track(frames([[box(100 + i * 10, 100)] for i in range(8)]))

    centres = tracks[0].centres()
    assert len(centres) == 8
    timestamps = [timestamp for timestamp, _, _ in centres]
    assert timestamps == sorted(timestamps)
    # Moving right: x must increase.
    xs = [x for _, x, _ in centres]
    assert xs == sorted(xs)
