"""Phone number normalisation.

Phone is the identity in this product, so ``0612345678``, ``+212612345678`` and
``00212 612 345 678`` must all resolve to the same user. Everything is stored in
E.164; the default region is Morocco but any international number is accepted.
"""

from __future__ import annotations

import phonenumbers

from .errors import InvalidPhoneNumber

DEFAULT_REGION = "MA"


def normalize_phone(raw: str, *, region: str = DEFAULT_REGION) -> str:
    """Return the E.164 form, or raise :class:`InvalidPhoneNumber`."""
    candidate = (raw or "").strip()
    if not candidate:
        raise InvalidPhoneNumber()
    try:
        parsed = phonenumbers.parse(candidate, region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhoneNumber() from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneNumber()
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def mask_phone(phone: str) -> str:
    """``+212612345678`` → ``+2126••••678``. For logs and shared screens."""
    if len(phone) < 7:
        return "•" * len(phone)
    return f"{phone[:5]}{'•' * (len(phone) - 8)}{phone[-3:]}"
