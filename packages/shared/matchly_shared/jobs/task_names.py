"""Celery task names.

The API enqueues work with ``send_task(TASK_NAME, ...)`` and therefore never
imports worker code — the API image needs no ffmpeg, OpenCV or torch. These
strings are the contract between the two sides; changing one is a deployment
concern, so they live in exactly one place.
"""

from __future__ import annotations

#: Queue names. Two queues so a stuck AI model can never block clip generation.
QUEUE_VIDEO = "video"
QUEUE_AI = "ai"
QUEUE_DEFAULT = QUEUE_VIDEO

#: Orchestrates the whole pipeline for one video, step by step.
PROCESS_VIDEO = "matchly.video.process_video"
#: Runs (or re-runs) a single pipeline step. Backs admin "retry this job".
RUN_STEP = "matchly.video.run_step"
#: Generates a 9:16 export for one highlight, on demand from the share sheet.
EXPORT_VERTICAL_CLIP = "matchly.video.export_vertical_clip"

#: Periodic maintenance (celery beat).
PURGE_EXPIRED_VIDEOS = "matchly.maintenance.purge_expired_videos"
SWEEP_STALE_CAMERAS = "matchly.maintenance.sweep_stale_cameras"
REAP_STUCK_JOBS = "matchly.maintenance.reap_stuck_jobs"

__all__ = [
    "EXPORT_VERTICAL_CLIP",
    "PROCESS_VIDEO",
    "PURGE_EXPIRED_VIDEOS",
    "QUEUE_AI",
    "QUEUE_DEFAULT",
    "QUEUE_VIDEO",
    "REAP_STUCK_JOBS",
    "RUN_STEP",
    "SWEEP_STALE_CAMERAS",
]
