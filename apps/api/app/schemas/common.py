"""Shared response shapes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    """Base for anything serialised straight from a SQLAlchemy object."""

    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    code: str = Field(examples=["JERSEY_TAKEN"])
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """The envelope returned for every 4xx and 5xx."""

    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    service: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str = Field(examples=["ready", "degraded"])
    checks: dict[str, str]
