"""Highlight payloads."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from matchly_shared.domain import HighlightType, Team


class HighlightPlayerRef(BaseModel):
    id: uuid.UUID
    name: str
    team: Team
    jersey_number: int


class HighlightOut(BaseModel):
    id: uuid.UUID
    match_id: uuid.UUID
    start_time: float
    end_time: float
    duration: float
    score: float = Field(description="0–1 confidence from the detector.")
    type: HighlightType
    #: Signals that produced the score, e.g. {"motion": 0.94, "player_density": 0.88}.
    signals: dict[str, float | str] = {}
    #: Short-lived signed URLs. The buckets themselves stay private.
    video_url: str | None = None
    video_url_vertical: str | None = None
    thumbnail_url: str | None = None
    player: HighlightPlayerRef | None = None
    created_at: dt.datetime


class MatchHighlightsOut(BaseModel):
    match_id: uuid.UUID
    match_title: str | None
    total: int
    items: list[HighlightOut]
