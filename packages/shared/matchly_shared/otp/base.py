"""One-time-password delivery abstraction.

Phone number is the identity in this market, so OTP delivery is on the critical
path of every signup. The vendor will change (Twilio, Vonage, a local Moroccan SMS
gateway, or WhatsApp Business), so the platform depends on this interface and
never on a vendor SDK.

Implementing a real provider means writing one ``send`` method.
"""

from __future__ import annotations

import abc
import dataclasses
import hashlib
import hmac
import secrets


class OtpDeliveryError(RuntimeError):
    """The provider could not deliver the code. Callers should surface a retry."""


@dataclasses.dataclass(frozen=True, slots=True)
class OtpMessage:
    phone: str
    code: str
    ttl_seconds: int

    def render(self) -> str:
        minutes = max(1, self.ttl_seconds // 60)
        return f"Matchly: your code is {self.code}. It expires in {minutes} minutes."


class OtpProvider(abc.ABC):
    """Delivers a code to a phone number."""

    #: True when the code may be echoed back through the API (development only).
    exposes_code: bool = False

    @abc.abstractmethod
    def send(self, message: OtpMessage) -> None: ...


def generate_code(length: int = 6) -> str:
    """Cryptographically random numeric code, zero-padded."""
    if not 4 <= length <= 10:
        raise ValueError("OTP length must be between 4 and 10 digits")
    upper = 10**length
    return str(secrets.randbelow(upper)).zfill(length)


def hash_code(code: str, *, secret: str) -> str:
    """Codes are stored hashed, like passwords — a DB leak must not grant logins."""
    return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()


def verify_code(code: str, code_hash: str, *, secret: str) -> bool:
    return hmac.compare_digest(hash_code(code, secret=secret), code_hash)
