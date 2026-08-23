"""Recording lifecycle, upload and processing payloads."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from matchly_shared.domain import JobStatus, JobStep, VideoStatus

from .common import ORMModel


# ── Upload ───────────────────────────────────────────────────────────────
class UploadTargetIn(BaseModel):
    kind: Literal["master", "segment"] = "master"
    segment_index: int | None = Field(
        default=None, ge=0, description="Required when kind is 'segment'."
    )
    content_type: str = "video/mp4"


class UploadTargetOut(BaseModel):
    """A presigned PUT target.

    The recording goes straight from the pitch to object storage; the API only
    ever hands out the URL. An 8–30 GB master must never pass through a request
    handler.
    """

    video_id: uuid.UUID
    kind: str
    segment_index: int | None
    bucket: str
    storage_key: str
    upload_url: str
    method: str
    expires_at: dt.datetime


class SegmentCompleteIn(BaseModel):
    segment_index: int = Field(ge=0)
    size_bytes: int | None = Field(default=None, ge=0)
    duration: float | None = Field(default=None, ge=0)


class SegmentOut(ORMModel):
    id: uuid.UUID
    segment_index: int
    size_bytes: int | None
    duration: float | None
    uploaded_at: dt.datetime | None


class UploadCompleteIn(BaseModel):
    expected_segments: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Number of segments the agent recorded. Omit when a single master "
            "file was uploaded. Completion fails while any index is missing."
        ),
    )


# ── Video & jobs ─────────────────────────────────────────────────────────
class JobOut(ORMModel):
    id: uuid.UUID
    step: JobStep
    status: JobStatus
    attempts: int
    max_attempts: int
    last_error: str | None
    started_at: dt.datetime | None
    finished_at: dt.datetime | None


class VideoOut(BaseModel):
    id: uuid.UUID
    match_id: uuid.UUID
    status: VideoStatus
    duration: float | None
    size_bytes: int | None
    width: int | None
    height: int | None
    fps: float | None
    has_audio: bool
    failure_reason: str | None
    purge_after: dt.datetime | None
    created_at: dt.datetime
    segments: list[SegmentOut] = []
    jobs: list[JobOut] = []
    #: Short-lived signed URL; the buckets themselves stay private.
    playback_url: str | None = None


class ProcessOut(BaseModel):
    video_id: uuid.UUID
    status: VideoStatus
    task_id: str | None = None
    forced: bool = False
    detail: str
