"""User profile payloads."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .auth import UserOut

__all__ = ["UserOut", "UserUpdateIn"]


class UserUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar: str | None = Field(default=None, max_length=2048)
