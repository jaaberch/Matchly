# Privacy

Matchly films people playing football on public-facing pitches. Privacy is a
design constraint from the first commit, not a later feature.

## No facial recognition

Players are identified by the jersey number they register at check-in, matched
against numbers read from the video. No face is detected, embedded, matched or
stored — at any point, in any phase. This is a product decision, not a
limitation of the current implementation.

## Consent

Check-in cannot complete without explicit participation consent, recorded on
`match_players.consent_at` with the time it was given. Each venue carries a
`recording_disclosure` shown on the join screen and posted at the pitch.

## Retention

| Artefact | Default | Configurable |
|---|---|---|
| Original recording | 90 days | per venue, `venues.video_retention_days` |
| Replay and clips | kept | small, and what players return for |

Each video carries a `purge_after` deadline set from its venue's policy. An
hourly job deletes originals past that deadline from object storage.

## Access

Buckets are private. There is no public object and no permanent URL. Every read —
replay, clip, thumbnail — goes through a short-lived signed URL issued by the API
after it has authorised the caller. Venue-scoped routes check membership in
`venue_members`, not merely the operator role bit.

## Deletion

**`DELETE /users/me`** anonymises the account: name, phone and avatar are
removed, `deleted_at` is set, and every refresh token is revoked immediately.

The row is retained rather than hard-deleted because `match_players` carries the
team and jersey number that *other* players' highlights were attributed against;
deleting it outright would corrupt other people's matches. What is removed is
everything identifying. The real phone number is released, so the same person can
sign up again as a genuinely new account.

**`DELETE /matches/{id}`** removes the match, its players, its video rows and its
highlights, and deletes every object under both bucket prefixes.

## Data collected

| Data | Why | Retention |
|---|---|---|
| Name | shown to other players in the match | until deletion |
| Phone number | it is the account identifier | until deletion |
| Team and jersey number | highlight attribution | life of the match |
| Match video | the product | venue retention policy |
| Highlight clips | the product | until match deletion |
| OTP challenges | login, rate limiting | short-lived rows |

Codes are stored as HMAC hashes, never in clear. Refresh tokens are stored
hashed, like passwords.
