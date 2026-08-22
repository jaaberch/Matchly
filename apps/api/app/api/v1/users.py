"""Current-user routes."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from ...schemas.user import UserOut, UserUpdateIn
from ...services import user_service
from ..deps import CurrentUser, SessionDep

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut, summary="Current profile")
def read_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut, summary="Update the current profile")
def update_me(payload: UserUpdateIn, session: SessionDep, user: CurrentUser) -> UserOut:
    updated = user_service.update_profile(
        session, user=user, name=payload.name, avatar=payload.avatar
    )
    return UserOut.model_validate(updated)


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the current account",
    description=(
        "Anonymises the account and revokes every session. Match participation rows "
        "are kept but de-identified so other players' matches stay intact."
    ),
)
def delete_me(session: SessionDep, user: CurrentUser) -> Response:
    user_service.delete_account(session, user=user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
