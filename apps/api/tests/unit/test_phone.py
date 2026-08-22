"""Phone normalisation: the identity key for the whole platform."""

from __future__ import annotations

import pytest

from app.core.errors import InvalidPhoneNumber
from app.core.phone import mask_phone, normalize_phone


@pytest.mark.parametrize(
    "raw",
    [
        "0612345678",
        "+212612345678",
        "00212612345678",
        "06 12 34 56 78",
        "+212 612-345-678",
    ],
)
def test_moroccan_formats_all_normalise_to_one_identity(raw: str) -> None:
    # A player typing their number any of these ways must reach the same account.
    assert normalize_phone(raw) == "+212612345678"


def test_international_numbers_are_accepted() -> None:
    assert normalize_phone("+33612345678") == "+33612345678"


@pytest.mark.parametrize("raw", ["", "   ", "abc", "12", "+212 000", "061234567890123"])
def test_invalid_numbers_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(raw)


def test_mask_keeps_only_the_ends() -> None:
    masked = mask_phone("+212612345678")
    assert masked.startswith("+2126")
    assert masked.endswith("678")
    assert "12345" not in masked
