"""Authentication payloads."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from matchly_shared.domain import UserRole

from .common import ORMModel


class RequestOtpIn(BaseModel):
    phone: str = Field(
        min_length=6,
        max_length=24,
        description="Local or international format; normalised to E.164 (default region MA).",
        examples=["0612345678", "+212612345678"],
    )


class RequestOtpOut(BaseModel):
    challenge_id: uuid.UUID
    phone: str = Field(description="Masked E.164 form.", examples=["+2126••••678"])
    expires_at: dt.datetime
    #: Present only when a development OTP provider is configured. Never in production.
    dev_code: str | None = None


class VerifyOtpIn(BaseModel):
    phone: str = Field(min_length=6, max_length=24)
    code: str = Field(min_length=4, max_length=10, examples=["123456"])
    #: Supplied on first login; ignored for an existing account.
    name: str | None = Field(default=None, max_length=120)


class UserOut(ORMModel):
    id: uuid.UUID
    name: str
    phone: str
    avatar: str | None = None
    role: UserRole
    created_at: dt.datetime


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")
    user: UserOut


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: str
