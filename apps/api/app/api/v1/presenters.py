"""Turn ORM objects into response models.

Kept out of both the routers and the services: routers stay about HTTP, services
stay about domain logic, and the nesting rules (which fields are safe to expose
to whom) live in exactly one place.
"""

from __future__ import annotations

import uuid

from matchly_shared.config import Settings
from matchly_shared.domain import Camera, Field, Match, MatchPlayer, Venue

from ...schemas.match import (
    FieldRef,
    MatchDetail,
    MatchPlayerOut,
    MatchSummary,
    VenueRef,
    VideoRef,
)
from ...schemas.venue import CameraOut, FieldOut, VenueDetail, VenueOut


def camera_out(camera: Camera, *, settings: Settings) -> CameraOut:
    return CameraOut(
        id=camera.id,
        field_id=camera.field_id,
        name=camera.name,
        status=camera.status,
        last_seen=camera.last_seen,
        online=camera.is_online(offline_after_seconds=settings.camera_offline_after_seconds),
    )


def field_out(field: Field, *, settings: Settings) -> FieldOut:
    camera = field.camera
    return FieldOut(
        id=field.id,
        venue_id=field.venue_id,
        name=field.name,
        created_at=field.created_at,
        camera_id=camera.id if camera else None,
        camera=camera_out(camera, settings=settings) if camera else None,
    )


def venue_detail(venue: Venue, *, settings: Settings) -> VenueDetail:
    """Venue with its fields and cameras.

    Built explicitly rather than by validating the ORM object: ``CameraOut.online``
    is derived from the heartbeat, so it has no attribute to read off the model.
    """
    return VenueDetail(
        **VenueOut.model_validate(venue).model_dump(),
        fields=[
            field_out(field, settings=settings)
            for field in sorted(venue.fields, key=lambda f: f.name)
        ],
    )


def player_out(player: MatchPlayer, *, viewer_id: uuid.UUID | None = None) -> MatchPlayerOut:
    return MatchPlayerOut(
        id=player.id,
        user_id=player.user_id,
        name=player.user.name,
        avatar=player.user.avatar,
        team=player.team,
        jersey_number=player.jersey_number,
        jersey_override=player.jersey_override,
        is_me=viewer_id is not None and player.user_id == viewer_id,
    )


def match_summary(match: Match, *, highlight_count: int = 0) -> MatchSummary:
    venue = match.field.venue
    return MatchSummary(
        id=match.id,
        title=match.title,
        status=match.status,
        starts_at=match.starts_at,
        ends_at=match.ends_at,
        join_code=match.join_code,
        venue=VenueRef(id=venue.id, name=venue.name, location=venue.location),
        field=FieldRef(id=match.field.id, name=match.field.name),
        player_count=len(match.players),
        highlight_count=highlight_count,
        video_url=match.video_url,
    )


def match_detail(
    match: Match, *, viewer_id: uuid.UUID | None = None, highlight_count: int = 0
) -> MatchDetail:
    summary = match_summary(match, highlight_count=highlight_count)
    players = sorted(match.players, key=lambda p: (p.team.value, p.jersey_number))
    return MatchDetail(
        **summary.model_dump(),
        created_at=match.created_at,
        players=[player_out(player, viewer_id=viewer_id) for player in players],
        video=(
            VideoRef(id=match.video.id, status=match.video.status, duration=match.video.duration)
            if match.video
            else None
        ),
    )
