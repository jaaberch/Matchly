"""Environment-driven configuration shared by every Matchly process.

One settings object, read from the environment, with safe development defaults.
Secrets never have a usable production default: `Settings.validate_for_environment`
refuses to start a non-development process that is still using a dev placeholder.
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-insecure-change-me"

Environment = Literal["development", "test", "staging", "production"]
StorageBackend = Literal["local", "s3"]
OtpProviderName = Literal["mock", "log"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Runtime ──────────────────────────────────────────────────────────
    environment: Environment = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    service_name: str = "matchly"

    # ── URLs ─────────────────────────────────────────────────────────────
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://matchly:matchly@localhost:5432/matchly"
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_echo: bool = False

    # ── Broker ───────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_task_always_eager: bool = False

    # ── Object storage ───────────────────────────────────────────────────
    # Originals and derived artefacts live in separate buckets so they can have
    # separate lifecycle policies: masters expire, clips are kept.
    storage_backend: StorageBackend = "local"
    storage_local_path: str = "./.storage"
    storage_bucket_originals: str = "matchly-originals"
    storage_bucket_derived: str = "matchly-derived"
    signed_url_ttl_seconds: int = 3600

    s3_endpoint_url: str | None = None  # set for R2 / MinIO, leave unset for AWS
    s3_region: str = "auto"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_force_path_style: bool = True  # MinIO needs it; R2 tolerates it
    s3_public_base_url: str | None = None

    # ── Authentication ───────────────────────────────────────────────────
    jwt_secret_key: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 60 * 15
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 30

    otp_provider: OtpProviderName = "mock"
    otp_code_length: int = 6
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_max_requests_per_window: int = 3
    otp_request_window_seconds: int = 600
    otp_expose_dev_code: bool = True  # only honoured when provider is mock/log

    # ── Domain knobs ─────────────────────────────────────────────────────
    camera_offline_after_seconds: int = 120
    default_video_retention_days: int = 90
    join_code_length: int = 6

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def is_development(self) -> bool:
        return self.environment in ("development", "test")

    def validate_for_environment(self) -> None:
        """Fail fast rather than run a production process with dev secrets."""
        if self.is_development:
            return
        problems: list[str] = []
        if self.jwt_secret_key == DEV_JWT_SECRET:
            problems.append("JWT_SECRET_KEY is still the development placeholder")
        if self.storage_backend == "local":
            problems.append("STORAGE_BACKEND=local is not valid outside development")
        if self.otp_provider in ("mock", "log"):
            problems.append(f"OTP_PROVIDER={self.otp_provider} cannot send real messages")
        if problems:
            raise RuntimeError(f"Refusing to start in {self.environment}: " + "; ".join(problems))


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Call `.cache_clear()` in tests."""
    return Settings()
