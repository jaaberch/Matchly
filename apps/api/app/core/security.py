"""Token issuing and verification.

Two token types:

* **access** — short-lived JWT, sent on every request, never stored server-side.
* **refresh** — long-lived opaque random string. Only its hash is stored, and it
  rotates on every use so a stolen refresh token is usable at most once before the
  legitimate client's next refresh invalidates it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from jose import JWTError, jwt

from matchly_shared.config import Settings
from matchly_shared.domain import UserRole
from matchly_shared.timeutil import utcnow

from .errors import InvalidToken

TokenType = Literal["access", "refresh"]


@dataclass(frozen=True, slots=True)
class TokenPayload:
    user_id: uuid.UUID
    role: UserRole
    token_type: TokenType
    expires_at: dt.datetime
    jti: str


def create_access_token(
    *, user_id: uuid.UUID, role: UserRole, settings: Settings
) -> tuple[str, int]:
    """Return ``(jwt, expires_in_seconds)``."""
    ttl = settings.access_token_ttl_seconds
    issued = utcnow()
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "role": role.value,
        "type": "access",
        "iat": int(issued.timestamp()),
        "exp": int((issued + dt.timedelta(seconds=ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, ttl


def decode_access_token(token: str, *, settings: Settings) -> TokenPayload:
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise InvalidToken() from exc

    if claims.get("type") != "access":
        raise InvalidToken("Expected an access token.")
    try:
        user_id = uuid.UUID(claims["sub"])
        role = UserRole(claims["role"])
    except (KeyError, ValueError) as exc:
        raise InvalidToken() from exc

    return TokenPayload(
        user_id=user_id,
        role=role,
        token_type="access",
        expires_at=dt.datetime.fromtimestamp(claims["exp"], dt.UTC),
        jti=claims.get("jti", ""),
    )


def generate_refresh_token() -> tuple[str, str]:
    """Return ``(raw_token, token_hash)``. Only the hash is ever persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_join_code(length: int = 6) -> str:
    """Human-friendly match code for QR links.

    Excludes characters that are easily confused when read aloud or typed on a
    phone at a noisy pitch: 0/O, 1/I/L.
    """
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))
