"""OTP provider selection."""

from __future__ import annotations

import functools

from ..config import Settings, get_settings
from .base import OtpProvider
from .mock import LoggingOtpProvider, MockOtpProvider


def build_otp_provider(settings: Settings) -> OtpProvider:
    if settings.otp_provider == "log":
        return LoggingOtpProvider()
    return MockOtpProvider()


@functools.lru_cache(maxsize=1)
def get_otp_provider() -> OtpProvider:
    """Process-wide provider singleton. Call `.cache_clear()` in tests."""
    return build_otp_provider(get_settings())
