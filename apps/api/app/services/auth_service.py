"""Phone + OTP authentication.

The flow is deliberately boring:

1. ``request_otp`` — normalise the phone, rate-limit, generate a code, store only
   its hash, hand the code to the configured provider.
2. ``verify_otp`` — find the newest live challenge, count the attempt *before*
   checking the code, consume it on success, then create or fetch the user and
   issue tokens.

Notes that matter for security:

* Codes are hashed, never stored in clear. A database dump grants no logins.
* Attempts are counted per challenge and committed before the code is checked,
  so a rejected attempt survives the failed request. Brute force therefore costs
  a new SMS every N tries.
* Requests are rate-limited by counting rows, not by an in-memory counter, so the
  limit survives restarts and applies across every API replica.
* Verifying an OTP consumes the challenge whether or not it succeeded fully, so a
  code cannot be replayed.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from matchly_shared.config import Settings
from matchly_shared.domain import OtpChallenge, RefreshToken, User, UserRole
from matchly_shared.logging import get_logger
from matchly_shared.otp import OtpMessage, OtpProvider, generate_code, hash_code, verify_code

from ..core.errors import (
    InvalidOtp,
    InvalidToken,
    NotFound,
    OtpExpired,
    RateLimited,
    TooManyAttempts,
)
from ..core.phone import mask_phone, normalize_phone
from ..core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)

logger = get_logger(__name__)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite hands back naive datetimes; treat stored times as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


class OtpRequestResult:
    __slots__ = ("challenge", "dev_code", "masked_phone")

    def __init__(self, challenge: OtpChallenge, dev_code: str | None, masked_phone: str) -> None:
        self.challenge = challenge
        self.dev_code = dev_code
        self.masked_phone = masked_phone


def request_otp(
    session: Session,
    *,
    raw_phone: str,
    settings: Settings,
    provider: OtpProvider,
) -> OtpRequestResult:
    phone = normalize_phone(raw_phone)

    window_start = _now() - dt.timedelta(seconds=settings.otp_request_window_seconds)
    recent = session.scalar(
        select(func.count())
        .select_from(OtpChallenge)
        .where(OtpChallenge.phone == phone, OtpChallenge.created_at >= window_start)
    )
    if (recent or 0) >= settings.otp_max_requests_per_window:
        logger.warning("otp.rate_limited", extra={"phone": mask_phone(phone)})
        raise RateLimited(
            "Too many codes requested for this number. Try again shortly.",
            details={"retry_after_seconds": settings.otp_request_window_seconds},
        )

    code = generate_code(settings.otp_code_length)
    challenge = OtpChallenge(
        phone=phone,
        code_hash=hash_code(code, secret=settings.jwt_secret_key),
        expires_at=_now() + dt.timedelta(seconds=settings.otp_ttl_seconds),
    )
    session.add(challenge)
    session.flush()

    provider.send(OtpMessage(phone=phone, code=code, ttl_seconds=settings.otp_ttl_seconds))
    logger.info(
        "otp.requested",
        extra={"phone": mask_phone(phone), "challenge_id": str(challenge.id)},
    )

    expose = provider.exposes_code and settings.otp_expose_dev_code and settings.is_development
    return OtpRequestResult(
        challenge=challenge,
        dev_code=code if expose else None,
        masked_phone=mask_phone(phone),
    )


def verify_otp(
    session: Session,
    *,
    raw_phone: str,
    code: str,
    name: str | None,
    settings: Settings,
) -> tuple[User, str, str, int]:
    """Return ``(user, access_token, refresh_token, expires_in)``."""
    phone = normalize_phone(raw_phone)

    challenge = session.scalars(
        select(OtpChallenge)
        .where(OtpChallenge.phone == phone, OtpChallenge.consumed_at.is_(None))
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
    ).first()

    if challenge is None:
        raise InvalidOtp("No code was requested for this number.")

    expires_at = _aware(challenge.expires_at)
    if expires_at is not None and expires_at < _now():
        raise OtpExpired()

    if challenge.attempts >= settings.otp_max_attempts:
        challenge.consumed_at = _now()
        session.commit()  # burn the challenge even though this request fails
        raise TooManyAttempts("Too many incorrect attempts. Request a new code.")

    # Count the attempt before validating, and commit it right away.
    # This request is about to fail, and a failing request is rolled back — a
    # counter that only lived in the request transaction would be discarded,
    # handing an attacker unlimited guesses against a 6-digit code.
    challenge.attempts += 1
    session.commit()

    if not verify_code(code, challenge.code_hash, secret=settings.jwt_secret_key):
        remaining = max(0, settings.otp_max_attempts - challenge.attempts)
        logger.info(
            "otp.verify_failed",
            extra={"phone": mask_phone(phone), "attempts_remaining": remaining},
        )
        raise InvalidOtp(details={"attempts_remaining": remaining})

    challenge.consumed_at = _now()
    user = _get_or_create_user(session, phone=phone, name=name)
    access_token, expires_in = create_access_token(
        user_id=user.id, role=user.role, settings=settings
    )
    refresh_token = _issue_refresh_token(session, user=user, settings=settings)

    logger.info("auth.login", extra={"user_id": str(user.id), "phone": mask_phone(phone)})
    return user, access_token, refresh_token, expires_in


def _get_or_create_user(session: Session, *, phone: str, name: str | None) -> User:
    user = session.scalars(
        select(User).where(User.phone == phone, User.deleted_at.is_(None))
    ).first()
    if user is not None:
        return user

    user = User(
        name=(name or "").strip() or f"Player {phone[-4:]}",
        phone=phone,
        role=UserRole.PLAYER,
    )
    session.add(user)
    session.flush()
    logger.info("user.created", extra={"user_id": str(user.id)})
    return user


def _issue_refresh_token(session: Session, *, user: User, settings: Settings) -> str:
    raw, token_hash = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=_now() + dt.timedelta(seconds=settings.refresh_token_ttl_seconds),
        )
    )
    session.flush()
    return raw


def refresh_tokens(
    session: Session, *, raw_refresh_token: str, settings: Settings
) -> tuple[User, str, str, int]:
    """Rotate a refresh token. The presented token is revoked before a new one is issued."""
    token_hash = hash_refresh_token(raw_refresh_token)
    stored = session.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    ).first()

    if stored is None or stored.revoked_at is not None:
        raise InvalidToken("This refresh token is no longer valid.")
    expires_at = _aware(stored.expires_at)
    if expires_at is not None and expires_at < _now():
        raise InvalidToken("This refresh token has expired.")

    user = session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise InvalidToken()

    stored.revoked_at = _now()
    access_token, expires_in = create_access_token(
        user_id=user.id, role=user.role, settings=settings
    )
    new_refresh = _issue_refresh_token(session, user=user, settings=settings)
    return user, access_token, new_refresh, expires_in


def revoke_refresh_token(session: Session, *, raw_refresh_token: str, user_id: uuid.UUID) -> None:
    """Log out. Revoking an unknown or already-revoked token is a no-op by design:
    logout must never fail and must never reveal whether a token existed."""
    stored = session.scalars(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(raw_refresh_token),
            RefreshToken.user_id == user_id,
        )
    ).first()
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = _now()


def revoke_all_refresh_tokens(session: Session, *, user_id: uuid.UUID) -> int:
    """Used by account deletion and by a future 'sign out everywhere'."""
    tokens = session.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    ).all()
    now = _now()
    for token in tokens:
        token.revoked_at = now
    return len(tokens)


def get_active_user(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise NotFound("User not found.")
    return user
