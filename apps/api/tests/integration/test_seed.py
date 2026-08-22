"""The development seed.

The seed is what lets the frontend be built before the AI pipeline exists, so it
has to be correct and re-runnable on every developer's machine.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.seed import seed
from matchly_shared.domain import (
    Camera,
    Field,
    Highlight,
    Match,
    MatchPlayer,
    MatchStatus,
    Team,
    User,
    Venue,
    Video,
    VideoStatus,
)


def test_seed_creates_the_demo_scenario(db: Session) -> None:
    seed(db)
    db.commit()

    venue = db.scalars(select(Venue)).one()
    assert venue.name == "Arena Demo Casablanca"
    assert venue.recording_disclosure  # the join screen needs it

    field = db.scalars(select(Field)).one()
    assert field.name == "Pitch 1"
    assert field.venue_id == venue.id

    camera = db.scalars(select(Camera)).one()
    assert camera.field_id == field.id
    # Field.camera_id is exposed from the relationship, not stored twice.
    assert field.camera_id == camera.id


def test_seed_creates_both_squads_with_the_right_numbers(db: Session) -> None:
    seed(db)
    db.commit()

    played = db.scalars(select(Match).where(Match.join_code == "DEMO01")).one()
    roster = {(player.user.name, player.team, player.jersey_number) for player in played.players}

    assert roster == {
        ("Youssef", Team.A, 7),
        ("Hamza", Team.A, 10),
        ("Mehdi", Team.A, 4),
        ("Amine", Team.B, 9),
        ("Omar", Team.B, 5),
        ("Adam", Team.B, 11),
    }
    assert all(player.consent_at is not None for player in played.players)


def test_seed_creates_a_ready_match_with_highlights(db: Session) -> None:
    seed(db)
    db.commit()

    played = db.scalars(select(Match).where(Match.join_code == "DEMO01")).one()
    assert played.status is MatchStatus.READY

    video = db.scalars(select(Video)).one()
    assert video.status is VideoStatus.READY
    assert video.duration == 3600.0
    # match.video_url is derived from the video row, never stored twice.
    assert played.video_url == video.processed_url

    highlights = db.scalars(select(Highlight).order_by(Highlight.score.desc())).all()
    assert len(highlights) == 10
    assert highlights[0].score == 0.91
    assert all(h.end_time > h.start_time for h in highlights)
    assert all(h.signals for h in highlights)
    # Some highlights are attributed, some are not — the UI must handle both.
    assert any(h.player_id is not None for h in highlights)
    assert any(h.player_id is None for h in highlights)


def test_seed_creates_an_upcoming_match_open_for_check_in(db: Session) -> None:
    seed(db)
    db.commit()

    upcoming = db.scalars(select(Match).where(Match.join_code == "DEMO02")).one()
    assert upcoming.status is MatchStatus.SCHEDULED
    assert upcoming.status.accepts_players
    assert upcoming.players == []


def test_seed_is_idempotent(db: Session) -> None:
    seed(db)
    db.commit()
    counts = {
        model: db.scalar(select(func.count()).select_from(model))
        for model in (User, Venue, Field, Camera, Match, MatchPlayer, Video, Highlight)
    }

    seed(db)
    db.commit()

    assert {model: db.scalar(select(func.count()).select_from(model)) for model in counts} == counts


def test_seeded_players_can_log_in(client, db: Session) -> None:
    seed(db)
    db.commit()

    requested = client.post("/api/v1/auth/request-otp", json={"phone": "+212600000001"})
    assert requested.status_code == 200

    verified = client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": "+212600000001", "code": requested.json()["dev_code"]},
    )

    assert verified.status_code == 200
    assert verified.json()["user"]["name"] == "Youssef"
