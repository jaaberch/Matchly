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

## Phase 2 — people and matches ✅ complete

**Delivered**

- Venues (admin-created), staff onboarding by phone, fields, one camera per field
- Camera status and capture-agent heartbeat authenticated by a per-camera token
  issued once at attach time and stored hashed
- `online` derived from `last_seen`, never read from the `status` column
- Match scheduling with generated join codes and double-booking protection
- Public QR check-in preview carrying no player identities
- Player check-in with consent, jersey duplicate prevention, and an operator
  override for the cases where a venue decides a clash is acceptable
- Roster management from the venue side: add, correct, remove
- Listing scoped by entitlement — admins see all, staff see their venues,
  players see the matches they joined
- Web: QR join screen with team/number picker, match page with live roster,
  home wired to real match data
- 192 tests, green on SQLite and PostgreSQL

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
