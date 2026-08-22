"""Deterministic object keys.

Every derived artefact has exactly one key, computed from ids that exist before
the work starts. That is what makes the pipeline steps idempotent: a retried step
overwrites its own output instead of creating a duplicate.

Layout::

    matchly-originals/  matches/{match_id}/video/{video_id}/master.mp4
                        matches/{match_id}/video/{video_id}/segments/{index:05d}.mp4
    matchly-derived/    videos/{video_id}/replay.mp4
                        videos/{video_id}/proxy.mp4
                        videos/{video_id}/frames/{index:06d}.jpg
                        videos/{video_id}/clips/{highlight_id}.mp4
                        videos/{video_id}/clips/{highlight_id}-vertical.mp4
                        videos/{video_id}/thumbs/{highlight_id}.jpg
"""

from __future__ import annotations

import uuid

UUIDLike = uuid.UUID | str


def _s(value: UUIDLike) -> str:
    return str(value)


# ── originals bucket ─────────────────────────────────────────────────────
def master_key(match_id: UUIDLike, video_id: UUIDLike) -> str:
    return f"matches/{_s(match_id)}/video/{_s(video_id)}/master.mp4"


def segment_key(match_id: UUIDLike, video_id: UUIDLike, index: int) -> str:
    return f"matches/{_s(match_id)}/video/{_s(video_id)}/segments/{index:05d}.mp4"


def match_original_prefix(match_id: UUIDLike) -> str:
    return f"matches/{_s(match_id)}/"


# ── derived bucket ───────────────────────────────────────────────────────
def replay_key(video_id: UUIDLike) -> str:
    return f"videos/{_s(video_id)}/replay.mp4"


def proxy_key(video_id: UUIDLike) -> str:
    return f"videos/{_s(video_id)}/proxy.mp4"


def frame_key(video_id: UUIDLike, index: int) -> str:
    return f"videos/{_s(video_id)}/frames/{index:06d}.jpg"


def clip_key(video_id: UUIDLike, highlight_id: UUIDLike, *, vertical: bool = False) -> str:
    suffix = "-vertical" if vertical else ""
    return f"videos/{_s(video_id)}/clips/{_s(highlight_id)}{suffix}.mp4"


def thumbnail_key(video_id: UUIDLike, highlight_id: UUIDLike) -> str:
    return f"videos/{_s(video_id)}/thumbs/{_s(highlight_id)}.jpg"


def video_derived_prefix(video_id: UUIDLike) -> str:
    return f"videos/{_s(video_id)}/"


def avatar_key(user_id: UUIDLike) -> str:
    return f"users/{_s(user_id)}/avatar.jpg"
