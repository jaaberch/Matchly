# API reference

Base path `/api/v1`. JSON only. Interactive docs at `/docs`.

Endpoints marked **planned** are specified in
[ARCHITECTURE.md](../ARCHITECTURE.md) and arrive in the phase noted; they are not
mounted until they work, so `/docs` only ever lists what is real.

## Conventions

### Errors

Every 4xx and 5xx returns the same envelope:

```json
{
  "error": {
    "code": "INVALID_OTP",
    "message": "That code is incorrect.",
    "details": { "attempts_remaining": 4 },
    "request_id": "9f2c…"
  }
}
```

Switch on `code`, never on `message` — messages get reworded and translated.
`request_id` is echoed in the `X-Request-ID` response header and appears in every
log line for that request.

| Code | Status | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Payload failed validation; `details.fields` lists what |
| `INVALID_PHONE` | 422 | Not a valid phone number |
| `NOT_AUTHENTICATED` | 401 | Missing or empty bearer token |
| `INVALID_TOKEN` | 401 | Token invalid, expired, revoked or the wrong type |
| `INVALID_OTP` | 400 | Wrong code; `details.attempts_remaining` counts down |
| `OTP_EXPIRED` | 400 | Code expired |
| `TOO_MANY_ATTEMPTS` | 429 | Challenge burned after too many wrong codes |
| `RATE_LIMITED` | 429 | Too many code requests for this number |
| `PERMISSION_DENIED` | 403 | Authenticated but not allowed |
| `NOT_FOUND` | 404 | No such resource |
| `CONFLICT` | 409 | Conflicts with current state |
| `JERSEY_TAKEN` | 409 | Number already used on that team |
| `MATCH_NOT_JOINABLE` | 409 | Match closed for check-in |
| `ALREADY_JOINED` | 409 | Player already in this match |
| `CONSENT_REQUIRED` | 422 | Check-in attempted without consent |
| `FIELD_DOUBLE_BOOKED` | 409 | Another match already occupies that window |
| `FIELD_NAME_TAKEN` | 409 | The venue already has a field with that name |
| `MATCH_NOT_EDITABLE` | 409 | A match can only be edited before it starts |
| `MATCH_ALREADY_STARTED` | 409 | Too late to leave the match |

### Pagination

`?page=1&page_size=20` (max 100):

```json
{ "items": [], "page": 1, "page_size": 20, "total": 137, "has_next": true }
```

### Authentication

`Authorization: Bearer <access_token>`. Access tokens last 15 minutes; refresh
tokens last 30 days and **rotate on every use** — the presented token is revoked
before the new pair is issued, so a stolen refresh token works at most once.

## Health

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness. Touches no dependency. Always 200 if the process is up |
| GET | `/health/ready` | Readiness. Checks Postgres and Redis; 503 if either is down |

## Auth

### `POST /auth/request-otp`

```json
{ "phone": "0612345678" }
```

Accepts local Moroccan or international format; everything is normalised to
E.164, so `0612345678`, `+212612345678` and `00212612345678` reach one account.

```json
{
  "challenge_id": "…",
  "phone": "+2126••••678",
  "expires_at": "2026-08-22T15:30:00Z",
  "dev_code": "123456"
}
```

`dev_code` appears only when a development OTP provider is configured. The
response never contains the full phone number.

Limits: 3 requests per number per 10 minutes.

### `POST /auth/verify-otp`

```json
{ "phone": "0612345678", "code": "123456", "name": "Youssef" }
```

`name` is used only when creating the account; it never renames an existing one.
Returns `access_token`, `refresh_token`, `expires_in` and `user`.

Codes are single-use, expire after 5 minutes, and allow 5 attempts. Each failed
attempt is committed before the code is checked, so a rejected guess is never
free — the counter survives the failed request.

### `POST /auth/refresh`

```json
{ "refresh_token": "…" }
```

Returns a new pair and revokes the old token.

### `POST /auth/logout`

Bearer required. Revokes the supplied refresh token. Always succeeds — it never
reveals whether the token existed.

## Users

| Method | Path | Notes |
|---|---|---|
| GET | `/users/me` | Current profile |
| PATCH | `/users/me` | `{name?, avatar?}` |
| DELETE | `/users/me` | Anonymises the account and revokes every session |
| GET | `/users/me/matches` | `?scope=all\|upcoming\|past`, paginated |
| GET | `/users/me/highlights` | **planned** — Phase 6 |

Deletion keeps the row but strips name, phone and avatar. Match participation
rows survive de-identified, because other players' highlights were attributed
against the team and jersey number they carry. The real phone number is released,
so the same person can sign up again as a new account.

## Matches

### `GET /matches`

Listing is **scoped by entitlement**, not by the filters supplied:

| Caller | Sees |
|---|---|
| `ADMIN` | every match |
| Venue staff | matches at venues they are a member of |
| Player | matches they have joined |

Filters (`venue_id`, `field_id`, `status`, `from`, `to`) narrow within that set
and never widen it — asking for another venue's `venue_id` returns an empty page,
not a 403 and not their matches. A roster says who played football where and when,
so a player who has joined nothing sees nothing.

### `POST /matches`

```json
{ "field_id": "…", "starts_at": "2026-08-23T18:00:00Z",
  "ends_at": "2026-08-23T19:00:00Z", "title": "Friday 6-a-side" }
```

Venue staff only, and only for a field at a venue they are a member of. Generates
a unique `join_code` (6 characters, excluding `0 O 1 I L` so it survives being
read off a card at a floodlit pitch).

Overlapping bookings on one field are refused with `FIELD_DOUBLE_BOOKED`: one
camera per field means one match at a time, and a double booking would produce a
recording attributed to the wrong match.

### `GET /matches/join/{join_code}` — public

The QR code target. Public because a player scans it before they have an account.

```json
{
  "match_id": "…", "title": "Friday 6-a-side", "status": "SCHEDULED",
  "venue_name": "Arena Demo Casablanca", "field_name": "Pitch 1",
  "recording_disclosure": "This pitch is recorded…",
  "joinable": true,
  "taken_jerseys": { "A": [7, 10], "B": [9] },
  "team_sizes": { "A": 2, "B": 1 },
  "already_joined": false, "my_team": null, "my_jersey_number": null
}
```

It carries **no player identities** — only which numbers are taken, which is all
that is needed to pick one. The `already_joined` fields are populated only when
the caller presents a token. Codes are matched case-insensitively.

### `POST /matches/{id}/join`

```json
{ "team": "A", "jersey_number": 7, "consent": true }
```

`consent` is mandatory; without it nothing is written and the call fails with
`CONSENT_REQUIRED`. Duplicate numbers within a team are refused with
`JERSEY_TAKEN` — the friendly pre-check is backed by a partial unique index, so
two players tapping `#7` at the same moment produce exactly one winner and one
`JERSEY_TAKEN`, never a 500 and never two rows.

Check-in is open while the match is `SCHEDULED` or `CHECK_IN`; anything later
returns `MATCH_NOT_JOINABLE`.

### Roster

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/matches/{id}/players` | participant or staff | Names only — never phone numbers |
| POST | `/matches/{id}/players` | staff | Check in a player who has no phone to hand |
| PATCH | `/matches/{id}/players/{player_id}` | staff | Correct a team or number |
| DELETE | `/matches/{id}/players/{player_id}` | staff | Remove from the roster |
| DELETE | `/matches/{id}/players/me` | participant | Leave, before the match starts |

`allow_duplicate_jersey: true` on the two staff endpoints is the administrator
override for a duplicate number. It sets `jersey_override` on the row, which
lifts it out of the partial unique index. Two players in the same shirt simply
will not be told apart by the pipeline.

### Other match routes

| Method | Path | Notes |
|---|---|---|
| GET | `/matches/{id}` | Visible to participants, venue staff and admins |
| PATCH | `/matches/{id}` | Reschedule or rename, only before the match starts |
| DELETE | `/matches/{id}` | Deletes the match and its roster (privacy) |
| GET | `/venues/{id}/matches` | Venue dashboard query; `?date=` filters to one day |
| GET | `/users/me/matches` | `?scope=all\|upcoming\|past` |

## Venues, fields and cameras

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/venues` | staff | Admins see all; operators see their own |
| POST | `/venues` | admin | Only the platform onboards venues |
| GET | `/venues/{id}` | member | Venue with fields and camera status |
| PATCH | `/venues/{id}` | manager | Settings, including `video_retention_days` |
| GET/POST | `/venues/{id}/members` | manager | Staff onboarding by phone number |
| GET/POST | `/venues/{id}/fields` | member | Field management |
| GET | `/fields/{id}` | member | Field with its camera |
| POST | `/fields/{id}/camera` | member | Attach or replace; returns the token once |
| DELETE | `/fields/{id}/camera` | member | Detach |
| GET | `/cameras/{id}/status` | member | `{status, last_seen, online, current_match_id}` |
| POST | `/cameras/{id}/heartbeat` | camera token | Capture agent liveness |

Two roles exist within a venue. `OPERATOR` covers day-to-day match work —
scheduling, rosters, starting and stopping. `MANAGER` is additionally required
for venue settings and staff changes.

**Camera credentials.** `POST /fields/{id}/camera` returns a `token` exactly once.
It is stored hashed and cannot be recovered; re-attaching the camera issues a new
one, which is also how a leaked token is rotated. The capture agent presents it in
the `X-Camera-Token` header — a machine credential, deliberately not a user token,
and the two do not interchange.

**Online is derived.** `online` is computed from `last_seen` against
`CAMERA_OFFLINE_AFTER_SECONDS`, never read from the `status` column. An agent that
dies without saying goodbye leaves `status=ONLINE` behind; a dashboard that trusted
that column would tell a venue everything was fine until after the match.

## Planned

| Method | Path | Phase |
|---|---|---|
| POST | `/matches/{id}/start`, `/stop` | 3 |
| POST | `/matches/{id}/video` | 3 |
| POST | `/matches/{id}/process` | 3 |
| GET | `/matches/{id}/highlights` | 4 |
| GET | `/users/me/highlights` | 6 |
| GET | `/admin/overview`, `/admin/jobs`, `/admin/storage` | 6 |
