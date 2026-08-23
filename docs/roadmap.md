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

## Phase 3 — video in ✅ complete

**Delivered**

- Idempotent match start/stop; starting refuses a field with no camera
- Presigned PUT uploads straight to object storage — an 8–30 GB master never
  passes through the API
- Segmented recording: each segment is verified in storage before it counts, and
  the upload is complete only when every index has arrived
- Uploads authenticated by venue staff *or* the field's capture agent
- ffprobe metadata extraction: duration, resolution, frame rate, audio
- `processing_jobs` orchestration: one row per (video, step), fingerprint-based
  idempotency, per-step errors, required-vs-skippable handling
- Stuck-job reaper, stale-camera sweep, retention purge on celery beat
- A broker outage returns a clear 503 saying the recording is safe

## Phase 4 — end-to-end with a mock detector ✅ complete

The entire journey works: record, upload, process, deliver.

**Delivered**

- TRANSCODE: 1080p replay (faststart, so playback begins immediately) plus a
  640p CV proxy; neither upscaled past the source
- SAMPLE_FRAMES: 2 fps sampling for the detection steps
- SCORE_EVENTS: pluggable `HighlightDetector` with `MockHighlightDetector`,
  temporal non-maximum suppression, top 10–20 by score
- CUT_CLIPS: one 16:9 clip per highlight plus a 9:16 social export; a single
  failed clip costs that clip, not the match
- THUMBNAILS and PERSIST: highlights without a clip are pruned, then MATCH READY
- Highlights API with short-lived signed URLs; no permanent public link
- Web: clips listed on the match page with thumbnails and inline playback
- 276 tests, green on SQLite and PostgreSQL, including a real ffmpeg run that
  uploads a recording in segments and asserts the clips it produces

**Verified end to end on the live stack:** a match scheduled through the API,
two players checked in, two 20-second segments uploaded by the capture-agent
token, processing queued on a real Celery worker, and three clips — with 9:16
exports and thumbnails — delivered to the player's phone screen.

## Phase 5 — real computer vision ✅ complete

**Delivered**

- YOLO player detection behind a `PlayerDetector` protocol, restricted to the
  person class, batched, with a frame cap so a backlog cannot take a day
- ByteTrack's two-stage association implemented directly: confident detections
  claim their tracks, then leftovers rescue the ones nothing claimed. That second
  stage is what keeps a player through an occlusion instead of splitting them
  into two half-length tracks
- Jersey recognition that goes back to the **master** for its crops — a player is
  a few dozen pixels tall on the 640p proxy and the number is unreadable, while
  the same crop from 4K is legible
- Confidence-weighted temporal voting with minimum votes, share and margin, and
  constrained matching against the numbers actually registered at check-in
- A heuristic detector fusing six signals — motion, acceleration, player density
  near goals, direction change, audio peaks, clustering — with weights in config
- Highlight attribution: a clip is credited to the player whose identified track
  overlaps it longest
- 340 tests, green on SQLite and PostgreSQL

**The detector ladder.** "Every AI component has a fallback" is now structural
rather than a convention. Detectors register with a priority and a predicate
saying what data they need, and the pipeline asks for the best one the *available*
data supports:

| Priority | Detector | Needs | Where |
|---|---|---|---|
| 100 | `heuristic-v1` | player tracks | CV worker |
| 50 | `motion-v1` | the proxy, or sampled frames | media worker |
| 0 | `mock-v1` | nothing but a duration | media worker |

A worker without the CV dependencies never registers the top rung, so the ladder
simply falls through. Nothing catches an ImportError and nothing reads a feature
flag.

**One architectural correction.** `SCORE_EVENTS` was documented as an AI-queue
step. It is a *required* step, so a required step living only where the optional
CV runtime lives would mean no highlights at all whenever detection is
unavailable — precisely the dependency the design forbids. It now runs anywhere
and adapts to what it is given. `AI_STEPS` is the three genuinely optional ones.

## Phase 6 — the product surfaces

Player highlight viewer (16:9 and 9:16), venue dashboard, admin dashboard,
sharing to WhatsApp, Instagram and TikTok.

## Phase 7 — production hardening

Permissions review, rate limiting, monitoring, error budgets, storage lifecycle
policies, security review.
