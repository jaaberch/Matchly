"""User profile and account deletion."""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from matchly_shared.domain import User
from matchly_shared.logging import get_logger

from .auth_service import revoke_all_refresh_tokens

logger = get_logger(__name__)


def update_profile(
    session: Session, *, user: User, name: str | None = None, avatar: str | None = None
) -> User:
    if name is not None:
        user.name = name.strip()
    if avatar is not None:
        user.avatar = avatar or None
    session.flush()
    return user


def delete_account(session: Session, *, user: User) -> None:
    """Right-to-erasure.

    The row is kept but anonymised rather than hard-deleted, because
    ``match_players`` rows carry the team and jersey number that other players'
    highlights were attributed against; deleting them outright would corrupt other
    people's matches. What is removed is everything that identifies the person:
    name, phone and avatar. Sessions are revoked immediately.

    The phone is replaced rather than nulled (the column is NOT NULL) with a short
    per-user marker that fits ``varchar(20)``. Because the uniqueness index on
    ``phone`` is partial — it only covers live rows — releasing the real number
    lets the same person sign up again as a genuinely new account.
    """
    now = dt.datetime.now(dt.UTC)
    user.name = "Deleted player"
    user.phone = f"del-{user.id.hex[:12]}"  # 16 chars; must fit varchar(20)
    user.avatar = None
    user.deleted_at = now
    revoke_all_refresh_tokens(session, user_id=user.id)
    session.flush()
    logger.info("user.deleted", extra={"user_id": str(user.id)})
