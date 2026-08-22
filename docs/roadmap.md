# Roadmap

Each phase is gated on the previous one being green. The goal throughout is one
real football match recorded, processed and delivered end to end — not feature
breadth.

## Phase 1 — foundations ✅ complete

Repository structure, architecture documentation, Docker development
environment, PostgreSQL schema, FastAPI skeleton, Next.js skeleton, phone
authentication.

**Delivered**

- Monorepo: `apps/`, `packages/`, `services/`, `infra/`, `docs/`
- `ARCHITECTURE.md`: design, schema, API contracts, pipeline, top-10 risks
- `docker-compose.yml`: postgres, redis, minio, api, video-worker, ai-worker, beat, web
- 13 tables, 9 native enums, initial Alembic migration (verified up *and* down)
- Vendor-neutral object storage: local disk, MinIO, R2, S3
- OTP provider abstraction with a mock implementation
- Celery app, two queues, task-name contract; both workers boot and connect
- Phone → OTP → JWT with rotating refresh tokens; `/users/me`; account deletion
- Structured JSON logging with request-id correlation; liveness and readiness checks
- Next.js shell: login, home, highlights, profile; typed API client with auto-refresh
- Seed: Arena Demo Casablanca / Pitch 1, both squads, a processed match, 10 fake highlights
- 97 tests, green on SQLite and on PostgreSQL

## Phase 2 — people and matches

Venues, fields, cameras, match CRUD, player check-in, jersey selection with
duplicate prevention and admin override. Venue-membership permissions on every
venue-scoped route.

## Phase 3 — video in

Match start/stop, presigned upload, segment completion, storage wiring, ffprobe
metadata extraction, `processing_jobs` orchestration, retry and the stuck-job
reaper.

## Phase 4 — end-to-end with a mock detector

ffmpeg clipping, thumbnails, and a `MockHighlightDetector`. The entire journey —
record, upload, process, deliver — works before any computer vision exists.

## Phase 5 — real computer vision

YOLO player detection, ByteTrack tracking, jersey OCR with temporal voting,
heuristic highlight scoring. Every component behind an interface, every one
skippable.

## Phase 6 — the product surfaces

Player highlight viewer (16:9 and 9:16), venue dashboard, admin dashboard,
sharing to WhatsApp, Instagram and TikTok.

## Phase 7 — production hardening

Permissions review, rate limiting, monitoring, error budgets, storage lifecycle
policies, security review.
