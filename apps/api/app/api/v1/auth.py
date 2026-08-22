"""Authentication routes: phone → OTP → tokens."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from ...core.errors import InvalidToken
from ...schemas.auth import (
    LogoutIn,
    RefreshIn,
    RequestOtpIn,
    RequestOtpOut,
    TokenPair,
    UserOut,
    VerifyOtpIn,
)
from ...services import auth_service
from ..deps import CurrentUser, OtpProviderDep, SessionDep, SettingsDep

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/request-otp",
    response_model=RequestOtpOut,
    summary="Send a one-time code to a phone number",
    responses={
        422: {"description": "The phone number is not valid"},
        429: {"description": "Too many codes requested for this number"},
    },
)
def request_otp(
    payload: RequestOtpIn,
    session: SessionDep,
    settings: SettingsDep,
    provider: OtpProviderDep,
) -> RequestOtpOut:
    result = auth_service.request_otp(
        session, raw_phone=payload.phone, settings=settings, provider=provider
    )
    return RequestOtpOut(
        challenge_id=result.challenge.id,
        phone=result.masked_phone,
        expires_at=result.challenge.expires_at,
        dev_code=result.dev_code,
    )


@router.post(
    "/verify-otp",
    response_model=TokenPair,
    summary="Exchange a one-time code for tokens",
    responses={
        400: {"description": "The code is wrong or has expired"},
        429: {"description": "Too many incorrect attempts"},
    },
)
def verify_otp(
    payload: VerifyOtpIn,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenPair:
    user, access_token, refresh_token, expires_in = auth_service.verify_otp(
        session,
        raw_phone=payload.phone,
        code=payload.code,
        name=payload.name,
        settings=settings,
    )
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotate an access token",
    responses={401: {"description": "The refresh token is invalid, revoked or expired"}},
)
def refresh(payload: RefreshIn, session: SessionDep, settings: SettingsDep) -> TokenPair:
    user, access_token, refresh_token, expires_in = auth_service.refresh_tokens(
        session, raw_refresh_token=payload.refresh_token, settings=settings
    )
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
)
def logout(payload: LogoutIn, session: SessionDep, user: CurrentUser) -> Response:
    auth_service.revoke_refresh_token(
        session, raw_refresh_token=payload.refresh_token, user_id=user.id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router", "InvalidToken"]
