"""Development OTP providers. Neither one sends anything to a real phone."""

from __future__ import annotations

from ..logging import get_logger
from .base import OtpMessage, OtpProvider

logger = get_logger(__name__)


class MockOtpProvider(OtpProvider):
    """Records messages in memory and lets the API echo the code back.

    Used by ``OTP_PROVIDER=mock`` and by the test suite, which asserts against
    :attr:`sent`.
    """

    exposes_code = True

    def __init__(self) -> None:
        self.sent: list[OtpMessage] = []

    def send(self, message: OtpMessage) -> None:
        self.sent.append(message)
        logger.info("otp.mock.delivered", extra={"phone": message.phone, "code": message.code})

    def last_code_for(self, phone: str) -> str | None:
        for message in reversed(self.sent):
            if message.phone == phone:
                return message.code
        return None

    def clear(self) -> None:
        self.sent.clear()


class LoggingOtpProvider(OtpProvider):
    """Writes the code to the log. Useful when several developers share a stack."""

    exposes_code = True

    def send(self, message: OtpMessage) -> None:
        logger.warning(
            "otp.log.delivered — development only",
            extra={"phone": message.phone, "code": message.code},
        )
