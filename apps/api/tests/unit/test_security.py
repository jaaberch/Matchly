"""Token issuing and verification."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from jose import jwt

from app.core.errors import InvalidToken
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_join_code,
    generate_refresh_token,
    hash_refresh_token,
)
from matchly_shared.config import Settings
from matchly_shared.domain import UserRole


@pytest.fixture
def token_settings() -> Settings:
    return Settings(jwt_secret_key="unit-test-secret", access_token_ttl_seconds=900)


def test_access_token_round_trip(token_settings: Settings) -> None:
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(
        user_id=user_id, role=UserRole.VENUE_OPERATOR, settings=token_settings
    )
    payload = decode_access_token(token, settings=token_settings)

    assert payload.user_id == user_id
    assert payload.role is UserRole.VENUE_OPERATOR
    assert expires_in == 900


def test_token_signed_with_another_secret_is_rejected(token_settings: Settings) -> None:
    token, _ = create_access_token(
        user_id=uuid.uuid4(), role=UserRole.PLAYER, settings=token_settings
    )
    other = Settings(jwt_secret_key="a-different-secret")
    with pytest.raises(InvalidToken):
        decode_access_token(token, settings=other)


def test_expired_token_is_rejected(token_settings: Settings) -> None:
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "PLAYER",
            "type": "access",
            "exp": int((dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)).timestamp()),
        },
        token_settings.jwt_secret_key,
        algorithm=token_settings.jwt_algorithm,
    )
    with pytest.raises(InvalidToken):
        decode_access_token(expired, settings=token_settings)


def test_refresh_token_cannot_be_used_as_an_access_token(token_settings: Settings) -> None:
    # Token confusion: a refresh token presented as a bearer must not authenticate.
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "PLAYER",
            "type": "refresh",
            "exp": int((dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).timestamp()),
        },
        token_settings.jwt_secret_key,
        algorithm=token_settings.jwt_algorithm,
    )
    with pytest.raises(InvalidToken):
        decode_access_token(forged, settings=token_settings)


@pytest.mark.parametrize("garbage", ["", "not-a-token", "a.b.c"])
def test_malformed_tokens_are_rejected(token_settings: Settings, garbage: str) -> None:
    with pytest.raises(InvalidToken):
        decode_access_token(garbage, settings=token_settings)


def test_refresh_tokens_are_random_and_stored_hashed() -> None:
    raw_a, hash_a = generate_refresh_token()
    raw_b, _ = generate_refresh_token()

    assert raw_a != raw_b
    assert hash_a != raw_a
    assert hash_refresh_token(raw_a) == hash_a


def test_join_codes_avoid_ambiguous_characters() -> None:
    codes = {generate_join_code(6) for _ in range(200)}
    assert all(len(code) == 6 for code in codes)
    # 0/O and 1/I/L are unreadable on a printed QR card at a noisy pitch.
    assert not any(set(code) & set("01OIL") for code in codes)
    assert len(codes) > 190  # effectively no collisions
