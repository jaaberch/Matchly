"""Domain enumerations.

These names are persisted as native PostgreSQL enum types and are also the exact
strings used on the wire, so renaming a member is a migration *and* an API change.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    PLAYER = "PLAYER"
    VENUE_OPERATOR = "VENUE_OPERATOR"
    ADMIN = "ADMIN"


class VenueRole(StrEnum):
    OPERATOR = "OPERATOR"
    MANAGER = "MANAGER"


class CameraStatus(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    RECORDING = "RECORDING"
    ERROR = "ERROR"


class MatchStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    CHECK_IN = "CHECK_IN"
    RECORDING = "RECORDING"
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (MatchStatus.READY, MatchStatus.FAILED)

    @property
    def accepts_players(self) -> bool:
        """Players may still check in while the match has not kicked off."""
        return self in (MatchStatus.SCHEDULED, MatchStatus.CHECK_IN)


class Team(StrEnum):
    A = "A"
    B = "B"


class VideoStatus(StrEnum):
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class JobStep(StrEnum):
    VALIDATE = "VALIDATE"
    PROBE = "PROBE"
    TRANSCODE = "TRANSCODE"
    SAMPLE_FRAMES = "SAMPLE_FRAMES"
    DETECT_PLAYERS = "DETECT_PLAYERS"
    TRACK = "TRACK"
    JERSEY_OCR = "JERSEY_OCR"
    SCORE_EVENTS = "SCORE_EVENTS"
    CUT_CLIPS = "CUT_CLIPS"
    THUMBNAILS = "THUMBNAILS"
    PERSIST = "PERSIST"


#: Pipeline order. Steps not in ``REQUIRED_STEPS`` may fail without failing the match:
#: the platform degrades to a full replay plus motion-based highlights.
PIPELINE_ORDER: tuple[JobStep, ...] = (
    JobStep.VALIDATE,
    JobStep.PROBE,
    JobStep.TRANSCODE,
    JobStep.SAMPLE_FRAMES,
    JobStep.DETECT_PLAYERS,
    JobStep.TRACK,
    JobStep.JERSEY_OCR,
    JobStep.SCORE_EVENTS,
    JobStep.CUT_CLIPS,
    JobStep.THUMBNAILS,
    JobStep.PERSIST,
)

REQUIRED_STEPS: frozenset[JobStep] = frozenset(
    {
        JobStep.VALIDATE,
        JobStep.PROBE,
        JobStep.TRANSCODE,
        JobStep.SCORE_EVENTS,
        JobStep.CUT_CLIPS,
        JobStep.PERSIST,
    }
)

#: Steps that need the computer-vision runtime. Every one of them is optional:
#: a worker without the CV dependencies leaves them PENDING and the match still
#: completes.
#:
#: ``SCORE_EVENTS`` is deliberately *not* here even though it consumes CV output.
#: It is a required step, and a required step that could only run where the
#: optional CV runtime lives would mean no highlights at all whenever detection
#: is unavailable — which is exactly the dependency the architecture forbids.
#: Instead it runs anywhere and adapts: richer signals and player attribution
#: when tracks exist, motion-only scoring when they do not.
AI_STEPS: frozenset[JobStep] = frozenset(
    {
        JobStep.DETECT_PLAYERS,
        JobStep.TRACK,
        JobStep.JERSEY_OCR,
    }
)


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class HighlightType(StrEnum):
    GOAL_AREA_ACTION = "GOAL_AREA_ACTION"
    HIGH_INTENSITY = "HIGH_INTENSITY"
    CELEBRATION = "CELEBRATION"
    TEAM_BUILDUP = "TEAM_BUILDUP"
    GENERIC = "GENERIC"
