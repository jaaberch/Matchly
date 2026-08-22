"""Reusable FastAPI dependencies: settings, storage, OTP provider, auth, permissions."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from matchly_shared.config import Settings, get_settings
from matchly_shared.domain import User, UserRole, VenueMember
from matchly_shared.otp import OtpProvider, get_otp_provider
from matchly_shared.storage import ObjectStorage, get_storage

from ..core.errors import NotAuthenticated, PermissionDenied
from ..core.security import decode_access_token
from ..db.session import get_db
from ..services.auth_service import get_active_user

# auto_error=False so a missing header raises our own error envelope, not FastAPI's.
bearer_scheme = HTTPBearer(auto_error=False)

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_db)]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
OtpProviderDep = Annotated[OtpProvider, Depends(get_otp_provider)]


def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise NotAuthenticated()
    payload = decode_access_token(credentials.credentials, settings=settings)
    return get_active_user(session, payload.user_id)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_optional_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User | None:
    """For endpoints that are public but richer when signed in (e.g. the join screen)."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials, settings=settings)
        return get_active_user(session, payload.user_id)
    except Exception:
        return None


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role is not UserRole.ADMIN:
        raise PermissionDenied("Platform administrator access is required.")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def require_operator(user: CurrentUser) -> User:
    """Any venue operator or admin. Which *venue* they may touch is a separate check."""
    if user.role not in (UserRole.VENUE_OPERATOR, UserRole.ADMIN):
        raise PermissionDenied("Venue operator access is required.")
    return user


OperatorUser = Annotated[User, Depends(require_operator)]


def assert_venue_access(session: Session, *, user: User, venue_id) -> None:
    """Venue-scoped authorisation.

    Being a ``VENUE_OPERATOR`` is not enough: the user must be a member of *this*
    venue. Admins bypass the membership check.
    """
    if user.role is UserRole.ADMIN:
        return
    membership = (
        session.query(VenueMember)
        .filter(VenueMember.venue_id == venue_id, VenueMember.user_id == user.id)
        .first()
    )
    if membership is None:
        raise PermissionDenied("You do not have access to this venue.")


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")
