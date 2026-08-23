"""Settings parsing and the production safety guard."""

from __future__ import annotations

import pytest

from matchly_shared.config import DEV_JWT_SECRET, Settings


def test_defaults_are_development_friendly() -> None:
    settings = Settings()
    assert settings.is_development
    assert settings.storage_backend == "local"
    assert settings.otp_provider == "mock"


def test_cors_origins_accept_a_comma_separated_string() -> None:
    # docker-compose passes a plain string; a list must come out.
    settings = Settings(cors_origins="http://a.test, http://b.test")
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("http://localhost:3000", ["http://localhost:3000"]),
        ("http://a.test,http://b.test", ["http://a.test", "http://b.test"]),
        ("http://a.test, http://b.test", ["http://a.test", "http://b.test"]),
        ('["http://a.test"]', ["http://a.test"]),
    ],
)
def test_cors_origins_parse_from_the_environment(monkeypatch, raw: str, expected: list) -> None:
    """The env path, not the constructor path.

    pydantic-settings JSON-decodes list fields straight from the environment,
    before any validator runs — so a bare ``CORS_ORIGINS=http://localhost:3000``
    used to crash the process at startup. docker-compose passes exactly that,
    and constructing Settings(...) directly never exercised it.
    """
    monkeypatch.setenv("CORS_ORIGINS", raw)
    assert Settings().cors_origins == expected


def test_broker_falls_back_to_redis_url() -> None:
    settings = Settings(redis_url="redis://cache:6379/2")
    assert settings.broker_url == "redis://cache:6379/2"
    assert settings.result_backend == "redis://cache:6379/2"


def test_explicit_broker_wins() -> None:
    settings = Settings(redis_url="redis://cache:6379/0", celery_broker_url="redis://broker:6379/1")
    assert settings.broker_url == "redis://broker:6379/1"


def test_development_never_trips_the_guard() -> None:
    Settings(environment="development").validate_for_environment()


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"jwt_secret_key": DEV_JWT_SECRET}, "JWT_SECRET_KEY"),
        ({"jwt_secret_key": "real", "storage_backend": "local"}, "STORAGE_BACKEND"),
        (
            {"jwt_secret_key": "real", "storage_backend": "s3", "otp_provider": "mock"},
            "OTP_PROVIDER",
        ),
    ],
)
def test_production_refuses_to_start_with_development_settings(
    overrides: dict, expected: str
) -> None:
    base = {"environment": "production", "storage_backend": "s3", "otp_provider": "log"}
    settings = Settings(**{**base, **overrides})

    with pytest.raises(RuntimeError, match=expected):
        settings.validate_for_environment()


def test_a_fully_configured_production_setup_is_only_blocked_by_the_otp_provider() -> None:
    # Everything real except the OTP vendor, which Phase 1 does not ship yet.
    settings = Settings(
        environment="production",
        jwt_secret_key="a-real-secret-from-the-secret-manager",
        storage_backend="s3",
    )
    with pytest.raises(RuntimeError, match="OTP_PROVIDER"):
        settings.validate_for_environment()


def test_log_level_is_normalised() -> None:
    assert Settings(log_level="debug").log_level == "DEBUG"
