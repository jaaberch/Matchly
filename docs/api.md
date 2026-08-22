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
| GET | `/users/me/matches` | **planned** — Phase 2 |
| GET | `/users/me/highlights` | **planned** — Phase 6 |

Deletion keeps the row but strips name, phone and avatar. Match participation
rows survive de-identified, because other players' highlights were attributed
against the team and jersey number they carry. The real phone number is released,
so the same person can sign up again as a new account.

## Planned

| Method | Path | Phase |
|---|---|---|
| GET / POST | `/matches` | 2 |
| GET | `/matches/{id}` | 2 |
| GET | `/matches/join/{join_code}` | 2 |
| POST | `/matches/{id}/join` | 2 |
| POST | `/matches/{id}/start`, `/stop` | 3 |
| POST | `/matches/{id}/video` | 3 |
| POST | `/matches/{id}/process` | 3 |
| GET | `/matches/{id}/highlights` | 4 |
| GET / POST | `/venues`, `/venues/{id}/matches`, `/venues/{id}/fields` | 2 |
| GET | `/cameras/{id}/status`, POST `/cameras/{id}/heartbeat` | 2 |
| GET | `/admin/overview`, `/admin/jobs`, `/admin/storage` | 6 |
