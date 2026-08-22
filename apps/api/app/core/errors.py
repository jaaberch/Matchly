"""Application errors and their wire format.

Every failure the client can act on is an :class:`AppError` with a stable ``code``.
The frontend switches on the code, never on the message text, so messages can be
reworded or translated without breaking anything.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, client-facing failures."""

    code = "INTERNAL_ERROR"
    status_code = 500
    message = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_payload(self, request_id: str | None = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        if request_id:
            error["request_id"] = request_id
        return {"error": error}


# ── 400 family ───────────────────────────────────────────────────────────
class ValidationFailed(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422
    message = "The request payload is invalid."


class InvalidPhoneNumber(AppError):
    code = "INVALID_PHONE"
    status_code = 422
    message = "That phone number is not valid."


class NotAuthenticated(AppError):
    code = "NOT_AUTHENTICATED"
    status_code = 401
    message = "Authentication is required."


class InvalidToken(AppError):
    code = "INVALID_TOKEN"
    status_code = 401
    message = "The token is invalid or has expired."


class InvalidOtp(AppError):
    code = "INVALID_OTP"
    status_code = 400
    message = "That code is incorrect."


class OtpExpired(AppError):
    code = "OTP_EXPIRED"
    status_code = 400
    message = "That code has expired. Request a new one."


class TooManyAttempts(AppError):
    code = "TOO_MANY_ATTEMPTS"
    status_code = 429
    message = "Too many attempts. Try again later."


class RateLimited(AppError):
    code = "RATE_LIMITED"
    status_code = 429
    message = "Too many requests. Try again in a moment."


class PermissionDenied(AppError):
    code = "PERMISSION_DENIED"
    status_code = 403
    message = "You do not have access to this resource."


class NotFound(AppError):
    code = "NOT_FOUND"
    status_code = 404
    message = "Resource not found."


class Conflict(AppError):
    code = "CONFLICT"
    status_code = 409
    message = "That action conflicts with the current state."


# ── domain-specific (used from Phase 2 onwards) ──────────────────────────
class JerseyTaken(Conflict):
    code = "JERSEY_TAKEN"
    message = "That jersey number is already taken on this team."


class MatchNotJoinable(Conflict):
    code = "MATCH_NOT_JOINABLE"
    message = "This match is no longer open for check-in."


class AlreadyJoined(Conflict):
    code = "ALREADY_JOINED"
    message = "You have already joined this match."


class ConsentRequired(AppError):
    code = "CONSENT_REQUIRED"
    status_code = 422
    message = "Participation consent is required to join this match."
