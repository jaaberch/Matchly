# Video processing pipeline

Full design in [ARCHITECTURE.md §7](../ARCHITECTURE.md#7-asynchronous-video-processing-workflow).
This document is the operational view: what each step does, what happens when it
fails, and how to retry it.

## Steps

| # | Step | Queue | Output | On failure |
|---|---|---|---|---|
| 1 | `VALIDATE` | video | object exists, header readable | **fail the match** |
| 2 | `PROBE` | video | duration, fps, resolution, audio | **fail the match** |
| 3 | `TRANSCODE` | video | 1080p replay + 640p CV proxy | **fail the match** |
| 4 | `SAMPLE_FRAMES` | video | 2 fps frames from the proxy | skip → generic highlights |
| 5 | `DETECT_PLAYERS` | ai | YOLO person boxes | **not implemented yet** — stays PENDING |
| 6 | `TRACK` | ai | ByteTrack tracks | **not implemented yet** — stays PENDING |
| 7 | `JERSEY_OCR` | ai | voted jersey per track | **not implemented yet** — stays PENDING |
| 8 | `SCORE_EVENTS` | ai | candidates → NMS → top 10–20 | **fail the match** |
| 9 | `CUT_CLIPS` | video | one clip per highlight | partial: keep what worked |
| 10 | `THUMBNAILS` | video | one JPEG per clip | skip → poster frame in the UI |
| 11 | `PERSIST` | video | write highlights, set `READY` | **fail the match** |

Steps 4–7 are skippable. If the AI worker is down, OOMs, or its model file is
missing, the match still reaches `READY` with a full replay and highlights.
**The AI is an enhancement, never a dependency.**

As of Phase 4, steps 5–7 have no implementation at all — and matches reach
`READY` anyway. A step nothing can run is recorded `PENDING`, not `FAILED`, which
is the same mechanism that will let those steps run on a separate GPU worker
later. `SCORE_EVENTS` currently uses `MockHighlightDetector`, which spreads
plausible candidates across the recording rather than watching the football; it
is seeded by video id so re-runs are stable.

## Idempotency

One `processing_jobs` row per `(video_id, step)`, enforced by a unique
constraint. Before running, a step checks whether it already succeeded with the
same input fingerprint; if so it is skipped. So:

- a retry resumes at the failed step instead of re-transcoding an hour of 4K
- object keys are deterministic (`{video_id}/clips/{highlight_id}.mp4`), so a
  re-run overwrites its own output rather than duplicating it
- `POST /matches/{id}/process?force=true` re-runs completed steps deliberately

## Retries

- Celery retries with exponential backoff, bounded by the job row's `max_attempts`
- Exhausted retries mark the step `FAILED` with `last_error`; skippable steps let
  the pipeline continue
- `task_acks_late` plus `reject_on_worker_lost`: a worker crash re-delivers the
  job instead of silently dropping it
- A beat task returns jobs stuck in `RUNNING` past a timeout to `PENDING`

## Retrying by hand

```bash
# One step
curl -X POST localhost:8000/api/v1/admin/jobs/{job_id}/retry -H "Authorization: Bearer $ADMIN"

# The whole pipeline for a match, re-running completed steps
curl -X POST "localhost:8000/api/v1/matches/{id}/process?force=true" -H "Authorization: Bearer $OP"
```

## Why the proxy matters

A 60-minute 4K master is 8–30 GB and ~108,000 frames. Running detection over all
of it is roughly 100× the compute budget for a box serving five pitches. The
pipeline instead samples **2 fps from a 640p proxy** — about 7,200 small frames —
which is minutes of CPU. On seven-a-side pitches that is ample for the motion and
density signals the heuristic scorer uses.

## Storage

| Bucket | Contents | Lifecycle |
|---|---|---|
| `matchly-originals` | camera masters and segments | write-once; expires on the venue's retention policy |
| `matchly-derived` | replay, proxy, frames, clips, thumbnails | regenerable; kept longer |

Originals are never mutated. A pipeline bug cannot destroy a recording.
