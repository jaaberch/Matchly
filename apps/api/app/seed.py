"""Development seed data.

Creates the demo scenario from the product brief, including fake highlights so the
frontend can be built against realistic data long before the AI pipeline exists.

Idempotent: every row uses a deterministic UUID derived from a fixed namespace, so
``python -m app.seed`` can be run repeatedly without duplicating anything.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.orm import Session

from matchly_shared.config import get_settings
from matchly_shared.db import session_scope
from matchly_shared.domain import (
    Camera,
    CameraStatus,
    Field,
    Highlight,
    HighlightType,
    JobStatus,
    JobStep,
    Match,
    MatchPlayer,
    MatchStatus,
    ProcessingJob,
    Team,
    User,
    UserRole,
    Venue,
    VenueMember,
    VenueRole,
    Video,
    VideoStatus,
)
from matchly_shared.logging import configure_logging, get_logger
from matchly_shared.storage import keys

logger = get_logger(__name__)

#: Fixed namespace → the same seed ids on every machine, so a frontend developer's
#: hard-coded links keep working after a database reset.
NAMESPACE = uuid.UUID("6f1f4b2e-0000-4000-8000-000000000000")

DERIVED_BUCKET = "matchly-derived"
ORIGINALS_BUCKET = "matchly-originals"


def sid(*parts: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, ":".join(parts))


TEAM_A = [("Youssef", 7), ("Hamza", 10), ("Mehdi", 4)]
TEAM_B = [("Amine", 9), ("Omar", 5), ("Adam", 11)]

#: (offset_seconds, duration, score, type, scorer_name_or_None)
FAKE_HIGHLIGHTS = [
    (865, 18, 0.91, HighlightType.GOAL_AREA_ACTION, "Youssef"),
    (1432, 16, 0.87, HighlightType.GOAL_AREA_ACTION, "Amine"),
    (320, 14, 0.82, HighlightType.HIGH_INTENSITY, "Hamza"),
    (2510, 20, 0.79, HighlightType.CELEBRATION, "Omar"),
    (1890, 15, 0.74, HighlightType.TEAM_BUILDUP, None),
    (640, 12, 0.71, HighlightType.HIGH_INTENSITY, "Mehdi"),
    (2180, 17, 0.68, HighlightType.GOAL_AREA_ACTION, "Adam"),
    (1105, 13, 0.64, HighlightType.TEAM_BUILDUP, None),
    (2860, 19, 0.61, HighlightType.HIGH_INTENSITY, "Youssef"),
    (450, 14, 0.57, HighlightType.GENERIC, None),
]


def _upsert(session: Session, model, obj_id: uuid.UUID, **values):
    """Fetch by id or create. Existing rows are left alone so local edits survive."""
    existing = session.get(model, obj_id)
    if existing is not None:
        return existing
    instance = model(id=obj_id, **values)
    session.add(instance)
    session.flush()
    return instance


def seed(session: Session) -> dict[str, uuid.UUID]:
    settings = get_settings()
    now = dt.datetime.now(dt.UTC)

    # ── Staff ────────────────────────────────────────────────────────────
    admin = _upsert(
        session,
        User,
        sid("user", "admin"),
        name="Platform Admin",
        phone="+212600000000",
        role=UserRole.ADMIN,
    )
    operator = _upsert(
        session,
        User,
        sid("user", "operator"),
        name="Arena Operator",
        phone="+212600000099",
        role=UserRole.VENUE_OPERATOR,
    )

    # ── Venue graph ──────────────────────────────────────────────────────
    venue = _upsert(
        session,
        Venue,
        sid("venue", "arena-demo-casablanca"),
        name="Arena Demo Casablanca",
        location="Boulevard Zerktouni, Casablanca",
        timezone="Africa/Casablanca",
        video_retention_days=settings.default_video_retention_days,
        recording_disclosure=(
            "This pitch is recorded for highlight generation. By checking in you "
            "consent to appear in the match recording and in clips shared with the "
            "players of this match. No facial recognition is used."
        ),
    )
    _upsert(
        session,
        VenueMember,
        sid("venue-member", "operator"),
        venue_id=venue.id,
        user_id=operator.id,
        role=VenueRole.MANAGER,
    )

    field = _upsert(session, Field, sid("field", "pitch-1"), venue_id=venue.id, name="Pitch 1")
    _upsert(
        session,
        Camera,
        sid("camera", "pitch-1"),
        field_id=field.id,
        name="Pitch 1 — wide 4K",
        status=CameraStatus.ONLINE,
        stream_url="rtsp://camera-pitch-1.local:554/stream",
        last_seen=now,
    )

    # ── Players ──────────────────────────────────────────────────────────
    players: dict[str, User] = {}
    for index, (name, _) in enumerate(TEAM_A + TEAM_B, start=1):
        players[name] = _upsert(
            session,
            User,
            sid("user", name.lower()),
            name=name,
            phone=f"+21260000{index:04d}",
            role=UserRole.PLAYER,
        )

    # ── A finished match, fully processed, with highlights ───────────────
    played_start = (now - dt.timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    played = _upsert(
        session,
        Match,
        sid("match", "played"),
        field_id=field.id,
        starts_at=played_start,
        ends_at=played_start + dt.timedelta(minutes=60),
        status=MatchStatus.READY,
        join_code="DEMO01",
        title="Team A vs Team B",
        created_by=operator.id,
        started_at=played_start,
        stopped_at=played_start + dt.timedelta(minutes=60),
    )

    roster: dict[str, MatchPlayer] = {}
    for team, squad in ((Team.A, TEAM_A), (Team.B, TEAM_B)):
        for name, jersey in squad:
            roster[name] = _upsert(
                session,
                MatchPlayer,
                sid("match-player", "played", name.lower()),
                match_id=played.id,
                user_id=players[name].id,
                team=team,
                jersey_number=jersey,
                consent_at=played_start - dt.timedelta(minutes=15),
            )

    video_id = sid("video", "played")
    video = _upsert(
        session,
        Video,
        video_id,
        match_id=played.id,
        original_url=f"s3://{ORIGINALS_BUCKET}/{keys.master_key(played.id, video_id)}",
        processed_url=f"s3://{DERIVED_BUCKET}/{keys.replay_key(video_id)}",
        proxy_url=f"s3://{DERIVED_BUCKET}/{keys.proxy_key(video_id)}",
        duration=3600.0,
        status=VideoStatus.READY,
        size_bytes=8_100_000_000,
        width=3840,
        height=2160,
        fps=30.0,
        has_audio=True,
        video_metadata={"seeded": True, "codec": "h264"},
        purge_after=now + dt.timedelta(days=venue.video_retention_days),
    )

    # Job history, so the admin dashboard has something real to render.
    for step in JobStep:
        _upsert(
            session,
            ProcessingJob,
            sid("job", "played", step.value),
            video_id=video.id,
            step=step,
            status=JobStatus.SUCCEEDED,
            attempts=1,
            fingerprint="seed",
            result={"seeded": True},
            started_at=played_start + dt.timedelta(minutes=61),
            finished_at=played_start + dt.timedelta(minutes=63),
        )

    for index, (start, duration, score, kind, scorer) in enumerate(FAKE_HIGHLIGHTS):
        highlight_id = sid("highlight", "played", str(index))
        _upsert(
            session,
            Highlight,
            highlight_id,
            match_id=played.id,
            video_id=video.id,
            player_id=roster[scorer].id if scorer else None,
            start_time=float(start),
            end_time=float(start + duration),
            score=score,
            type=kind,
            video_url=f"s3://{DERIVED_BUCKET}/{keys.clip_key(video.id, highlight_id)}",
            video_url_vertical=(
                f"s3://{DERIVED_BUCKET}/{keys.clip_key(video.id, highlight_id, vertical=True)}"
            ),
            thumbnail_url=f"s3://{DERIVED_BUCKET}/{keys.thumbnail_key(video.id, highlight_id)}",
            signals={
                "motion": round(min(0.99, score + 0.03), 2),
                "player_density": round(max(0.1, score - 0.03), 2),
                "audio_peak": round(max(0.1, score - 0.15), 2),
            },
        )

    # ── An upcoming match, open for check-in ─────────────────────────────
    upcoming_start = (now + dt.timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    _upsert(
        session,
        Match,
        sid("match", "upcoming"),
        field_id=field.id,
        starts_at=upcoming_start,
        ends_at=upcoming_start + dt.timedelta(minutes=60),
        status=MatchStatus.SCHEDULED,
        join_code="DEMO02",
        title="Friday night 6-a-side",
        created_by=operator.id,
    )

    return {
        "admin_id": admin.id,
        "operator_id": operator.id,
        "venue_id": venue.id,
        "field_id": field.id,
        "played_match_id": played.id,
        "upcoming_match_id": sid("match", "upcoming"),
        "video_id": video.id,
    }


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt="console", service="matchly-seed")
    with session_scope() as session:
        result = seed(session)
    print("Seeded the demo scenario:")
    print("  venue        Arena Demo Casablanca / Pitch 1")
    print("  played match Team A vs Team B  ·  join code DEMO01  ·  10 highlights")
    print("  upcoming     Friday night 6-a-side  ·  join code DEMO02")
    print("  players      Youssef 7, Hamza 10, Mehdi 4  vs  Amine 9, Omar 5, Adam 11")
    print(f"  match id     {result['played_match_id']}")
    print("\nLog in with any seeded phone (e.g. +212600000001) — the mock OTP")
    print("provider returns the code in the request-otp response as `dev_code`.")


if __name__ == "__main__":
    main()
