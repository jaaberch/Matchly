# Matchly

[![CI](https://github.com/jaaberch/Matchly/actions/workflows/ci.yml/badge.svg)](https://github.com/jaaberch/Matchly/actions/workflows/ci.yml)

AI-powered football recording and highlights for small pitches.

A fixed 4K camera records a 60-minute match. Players check in by scanning a QR
code and picking a team and jersey number. When the match ends, the recording is
uploaded, processed, and turned into per-player highlight clips they can watch
and share.

> **Status: Phase 5 complete.** The product works end to end and now sees the
> football: YOLO finds the players, ByteTrack follows them, jersey numbers are
> read from the master and settled by a vote across each track, and highlights
> are scored from six signals and credited to the player they belong to. All of
> it degrades — a deployment without the computer-vision runtime still delivers
> a full replay and motion-scored clips. Phase 6 builds the venue and admin
> dashboards and sharing. See [ARCHITECTURE.md](ARCHITECTURE.md) for the design
> and [docs/roadmap.md](docs/roadmap.md) for what lands when.

---

## Quickstart

```bash
cp .env.example .env
make up          # postgres, redis, minio, api, workers, web
make migrate     # create the schema
make seed        # load the demo match
```

| What | Where |
|---|---|
| API docs | http://localhost:8000/docs |
| Web app | http://localhost:3000 |
| MinIO console | http://localhost:9001 |

Sign in at http://localhost:3000/login with any phone number — for example
`0612345678`, or a seeded player such as `+212600000001` (Youssef). The mock OTP
provider returns the code in the API response and the login screen fills it in,
so development needs no SMS vendor.

To walk the check-in journey, open http://localhost:3000/match/join/DEMO02 —
that is what the QR code on the pitch points at. Sign in as
`+212600000099` (the seeded venue operator) to schedule matches.

To watch a recording go all the way through:

```bash
make demo    # schedules a match, uploads a generated recording, processes it
```

### Without Docker

```bash
make bootstrap                      # virtualenv + editable installs
export DATABASE_URL=... REDIS_URL=...
cd apps/api && alembic upgrade head && python -m app.seed
uvicorn app.main:app --reload
```

---

## Repository layout

```
apps/api            FastAPI service — REST, auth, permissions, migrations
apps/web            Next.js app — player, venue and admin interfaces
packages/shared     matchly_shared — domain models, storage, OTP, Celery app
services/video-worker   ffmpeg: probe, transcode, clip, thumbnail
services/ai-worker      detection, tracking, jersey OCR, highlight scoring
infra/              Dockerfiles and helper scripts
docs/               architecture notes, roadmap, runbook
```

Three processes share one Python library. The API never touches video bytes — it
enqueues work by task name — so its image carries no ffmpeg, OpenCV or torch.

---

## Commands

```bash
make help          # list everything
make up / down     # start / stop the stack
make migrate       # apply migrations
make seed          # load the demo match (idempotent)
make test          # run the test suite (SQLite, no services needed)
make lint / fmt    # ruff
make logs S=api    # tail one service
make reset         # wipe the database, migrate, reseed
```

### Tests

```bash
make test                                              # fast, SQLite
TEST_DATABASE_URL=postgresql+psycopg://... make test    # against real Postgres
```

The same suite runs on both. SQLite keeps the loop fast; the PostgreSQL run is
what catches things SQLite quietly tolerates, such as column length limits.

CI runs the suite twice on every push and pull request: once **without** the
computer-vision runtime, which is a real deployment shape and proves a match
still completes on motion-scored highlights alone, and once **with** it. A third
job typechecks and builds the web app.

The video tests skip themselves when ffmpeg is missing, which is right on a
laptop and dangerous in CI — a green tick over nothing. `tests/test_toolchain.py`
fails the build when the environment claims a runtime it does not have.

---

## Configuration

Every setting is an environment variable, documented in
[`.env.example`](.env.example). No secrets are committed, and the API refuses to
start outside development while `JWT_SECRET_KEY` is still the placeholder.

Two abstractions exist because the vendor behind them will change:

- **Object storage** — `local` (disk) or `s3`, which serves MinIO in development
  and Cloudflare R2 or AWS S3 in production, unchanged.
- **OTP delivery** — `mock` in development. Adding a real SMS vendor means
  implementing one `send` method in
  `packages/shared/matchly_shared/otp/base.py`.

---

## Design rules

These hold across every phase:

- **A recording is never lost.** The capture agent buffers segments on local disk
  and uploads them resumably; a worker crash cannot destroy a match.
- **Original video is never mutated.** Masters and derived clips live in separate
  buckets with separate lifecycles.
- **Every AI component has a fallback**, structurally rather than by convention.
  Detectors register with a priority and a predicate describing what data they
  need; the pipeline asks for the best one the *available* data supports. A
  worker without the CV runtime never registers the top rung and the ladder falls
  through to motion-based scoring. The AI is an enhancement, never a dependency.
- **No video work in request handlers.** The API enqueues; workers process.
- **Jobs are idempotent.** One row per (video, step); retrying resumes at the
  failed step rather than re-transcoding an hour of 4K.
- **No facial recognition.** Players are identified by the jersey number they
  register at check-in.

---

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, schema, API contracts, pipeline, risks |
| [docs/api.md](docs/api.md) | Endpoint reference and error codes |
| [docs/pipeline.md](docs/pipeline.md) | Processing steps, retries, fallbacks |
| [docs/privacy.md](docs/privacy.md) | Consent, retention, deletion |
| [docs/roadmap.md](docs/roadmap.md) | Phase plan and current status |
| [docs/runbook.md](docs/runbook.md) | Operating the stack, common failures |
