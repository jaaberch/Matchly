"""OTP code generation, hashing and the mock provider."""

from __future__ import annotations

import pytest

from matchly_shared.otp import (
    MockOtpProvider,
    OtpMessage,
    generate_code,
    hash_code,
    verify_code,
)

SECRET = "otp-unit-secret"


@pytest.mark.parametrize("length", [4, 6, 8])
def test_generated_codes_have_the_requested_length(length: int) -> None:
    code = generate_code(length)
    assert len(code) == length
    assert code.isdigit()


def test_short_codes_are_padded_not_truncated() -> None:
    # A code of "42" must render as "000042", or the SMS text is wrong.
    assert all(len(generate_code(6)) == 6 for _ in range(500))


@pytest.mark.parametrize("length", [3, 11])
def test_absurd_lengths_are_rejected(length: int) -> None:
    with pytest.raises(ValueError):
        generate_code(length)


def test_codes_are_not_predictable() -> None:
    assert len({generate_code(6) for _ in range(200)}) > 150


def test_hash_verifies_and_is_not_reversible() -> None:
    code = "123456"
    hashed = hash_code(code, secret=SECRET)

    assert hashed != code
    assert verify_code(code, hashed, secret=SECRET)
    assert not verify_code("654321", hashed, secret=SECRET)


def test_hash_is_bound_to_the_server_secret() -> None:
    # A leaked database without the secret must not yield working codes.
    hashed = hash_code("123456", secret=SECRET)
    assert not verify_code("123456", hashed, secret="a-different-secret")


def test_message_text_mentions_the_code_and_expiry() -> None:
    rendered = OtpMessage(phone="+212612345678", code="123456", ttl_seconds=300).render()
    assert "123456" in rendered
    assert "5 minutes" in rendered


def test_mock_provider_records_what_it_sent() -> None:
    provider = MockOtpProvider()
    provider.send(OtpMessage(phone="+212612345678", code="111111", ttl_seconds=300))
    provider.send(OtpMessage(phone="+212612345678", code="222222", ttl_seconds=300))
    provider.send(OtpMessage(phone="+212699999999", code="333333", ttl_seconds=300))

    assert provider.last_code_for("+212612345678") == "222222"
    assert provider.last_code_for("+212699999999") == "333333"
    assert provider.last_code_for("+212600000000") is None
