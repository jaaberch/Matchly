# Runbook

Operating the stack, and what to do when something breaks.

## Daily checks

```bash
make ps                # every service healthy?
make worker-ping       # both workers consuming?
curl -s localhost:8000/health/ready | jq
```

`/health/ready` returns 503 with a per-dependency breakdown when Postgres or
Redis is unreachable. `/health` stays 200 as long as the process is alive — that
is the one an orchestrator should restart on.

## Tracing a failure

Every request gets an `X-Request-ID`, echoed in the response header and attached
to every log line emitted while handling it. Workers bind the job id the same
way.

```bash
make logs S=api | grep <request-id>
```

Logs are JSON in containers (`LOG_FORMAT=json`) and human-readable in a terminal
(`LOG_FORMAT=console`).

## Common failures

### A match is stuck in `UPLOADING`

Expected when the pitch's connection is poor. The capture agent buffers segments
on local disk and resumes; the match is not lost. Check which segments have
arrived before intervening.

### A match is stuck in `PROCESSING`

```sql
SELECT step, status, attempts, last_error, updated_at
FROM processing_jobs WHERE video_id = '<id>' ORDER BY updated_at;
```

A step in `RUNNING` well past its timeout means the worker died mid-step; the
reaper returns it to `PENDING` within five minutes. A step in `FAILED` on a
skippable step is fine — the match still completes with reduced attribution.

### A worker crashed mid-job

Nothing is lost. `task_acks_late` means the job is re-delivered, and step-level
idempotency means it resumes rather than restarting the pipeline.

### The camera shows offline

`online` is derived from the heartbeat, not stored: `last_seen` older than
`CAMERA_OFFLINE_AFTER_SECONDS` (default 120) reads as offline. Check the agent
before the camera — a stale heartbeat usually means the agent, not the hardware.

### The API will not start in staging or production

It refuses to boot while `JWT_SECRET_KEY` is the development placeholder,
`STORAGE_BACKEND=local`, or the OTP provider cannot send real messages. The error
names which one. This is deliberate.

## Database

```bash
make psql
make migrate                        # apply migrations
make migration M="add venues.city"  # autogenerate a new one
```

Always read a generated migration before committing it. Two things autogenerate
gets wrong on this schema: it does not emit `DROP TYPE` for native enums (so a
downgrade leaves them behind and the next upgrade fails), and it renders custom
column types without importing them. `alembic/env.py` handles the import via
`render_item`; enum drops are added by hand in the downgrade.

Verify both directions before merging:

```bash
alembic upgrade head && alembic downgrade base && alembic upgrade head
alembic check     # models and migrations agree
```

## Storage

```bash
mc ls local/matchly-originals --recursive --summarize
mc ls local/matchly-derived   --recursive --summarize
```

Originals are write-once and expire on the venue's retention policy. Derived
artefacts are regenerable: deleting a clip is safe, and re-running the pipeline
recreates it.
