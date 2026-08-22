"""Test fixtures.

Tests run against SQLite by default so they need no server and finish in seconds.
Set ``TEST_DATABASE_URL`` to a PostgreSQL URL to run the same suite against the
real production database engine — CI and ``make test-pg`` do exactly that.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

# Environment must be set before anything imports the settings singleton.
_TMP = Path(tempfile.mkdtemp(prefix="matchly-test-"))
os.environ.update(
    ENVIRONMENT="test",
    LOG_LEVEL="WARNING",
    LOG_FORMAT="console",
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}"),
    STORAGE_BACKEND="local",
    STORAGE_LOCAL_PATH=str(_TMP / "storage"),
    OTP_PROVIDER="mock",
    JWT_SECRET_KEY="test-secret-not-used-anywhere-real",
    CELERY_TASK_ALWAYS_EAGER="true",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.main import create_app  # noqa: E402
from matchly_shared.config import Settings, get_settings  # noqa: E402
from matchly_shared.db import get_engine, get_session_factory, reset_engine_cache  # noqa: E402
from matchly_shared.domain import Base  # noqa: E402
from matchly_shared.otp import MockOtpProvider, get_otp_provider  # noqa: E402
from matchly_shared.storage import get_storage  # noqa: E402


@pytest.fixture(scope="session")
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session", autouse=True)
def _database(settings: Settings) -> Iterator[None]:
    reset_engine_cache()
    get_storage.cache_clear()
    get_otp_provider.cache_clear()
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables(_database) -> Iterator[None]:
    """Truncate between tests so each one starts from a known state."""
    yield
    engine = get_engine()
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture
def db(_database) -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture
def otp(_database) -> Iterator[MockOtpProvider]:
    provider = get_otp_provider()
    assert isinstance(provider, MockOtpProvider)
    provider.clear()
    yield provider
    provider.clear()


@pytest.fixture
def client(settings: Settings, _database) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def auth(client: TestClient) -> AuthHelper:
    return AuthHelper(client)


class AuthHelper:
    """Signs a phone number in and returns usable headers.

    Every test that needs an authenticated caller goes through the real OTP flow,
    which keeps the auth path continuously exercised.
    """

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def login(self, phone: str = "+212612345678", name: str | None = "Test Player") -> dict:
        requested = self.client.post("/api/v1/auth/request-otp", json={"phone": phone})
        assert requested.status_code == 200, requested.text
        code = requested.json()["dev_code"]
        assert code, "the mock provider must expose the code in tests"

        verified = self.client.post(
            "/api/v1/auth/verify-otp", json={"phone": phone, "code": code, "name": name}
        )
        assert verified.status_code == 200, verified.text
        return verified.json()

    def headers(self, phone: str = "+212612345678") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.login(phone)['access_token']}"}
