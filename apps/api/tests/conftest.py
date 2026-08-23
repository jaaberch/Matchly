"""Test fixtures.

Tests run against SQLite by default so they need no server and finish in seconds.
Set ``TEST_DATABASE_URL`` to a PostgreSQL URL to run the same suite against the
real production database engine — CI and ``make test-pg`` do exactly that.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
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

from app.core.security import generate_join_code  # noqa: E402
from app.main import create_app  # noqa: E402
from matchly_shared.config import Settings, get_settings  # noqa: E402
from matchly_shared.db import get_engine, get_session_factory, reset_engine_cache  # noqa: E402
from matchly_shared.domain import (  # noqa: E402
    Base,
    Camera,
    Field,
    Match,
    MatchPlayer,
    MatchStatus,
    Team,
    User,
    UserRole,
    Venue,
    VenueMember,
    VenueRole,
)
from matchly_shared.otp import MockOtpProvider, get_otp_provider  # noqa: E402
from matchly_shared.storage import get_storage  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _media_steps() -> None:
    """Register the media worker's pipeline steps and detectors, once.

    Registration is an import side effect and imports happen once per process,
    so this is done at session scope and never undone. Tests that need a step or
    detector *absent* remove that specific entry (see `without_cv`), rather than
    trying to restore a registry snapshot that would be empty.
    """
    import video_worker.steps  # noqa: F401


@pytest.fixture
def without_cv() -> Iterator[None]:
    """Run as a worker that has no computer-vision runtime.

    Removes the CV steps and the track-based detector for one test, then puts
    back exactly what was removed.
    """
    from matchly_shared.domain import JobStep
    from matchly_shared.highlights import registry as detector_registry
    from matchly_shared.pipeline import registry as step_registry

    cv_steps = {
        step: step_registry._REGISTRY.pop(step)
        for step in (JobStep.DETECT_PLAYERS, JobStep.TRACK, JobStep.JERSEY_OCR)
        if step in step_registry._REGISTRY
    }
    heuristic = detector_registry._REGISTRY.pop("heuristic", None)
    try:
        yield
    finally:
        step_registry._REGISTRY.update(cv_steps)
        if heuristic is not None:
            detector_registry._REGISTRY["heuristic"] = heuristic


@pytest.fixture
def with_cv() -> None:
    """Register the computer-vision steps, if this environment has them."""
    pytest.importorskip("ai_worker.detection")
    import ai_worker.steps  # noqa: F401


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
        self._sessions: dict[str, dict] = {}

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

    def headers(self, phone: str = "+212612345678", name: str | None = None) -> dict[str, str]:
        """Bearer headers for a phone, signing in once and reusing the token.

        OTP requests are rate limited per number, so a test that needs the same
        caller several times must not repeat the whole flow each time.
        """
        if phone not in self._sessions:
            self._sessions[phone] = self.login(phone, name=name or "Test Player")
        return {"Authorization": f"Bearer {self._sessions[phone]['access_token']}"}

    def forget(self, phone: str) -> None:
        self._sessions.pop(phone, None)


# ── Domain factories ─────────────────────────────────────────────────────
@pytest.fixture
def factory(db: Session) -> Factory:
    return Factory(db)


class Factory:
    """Builds domain rows directly.

    Tests use this for *arranging* state — creating a venue with staff through
    the API every time would bury what each test is actually about. The flows
    being tested always go through HTTP.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def _add(self, instance):
        self.session.add(instance)
        self.session.commit()
        return instance

    def user(self, *, phone: str, name: str | None = None, role=UserRole.PLAYER) -> User:
        return self._add(User(name=name or f"User {phone[-4:]}", phone=phone, role=role))

    def venue(self, *, name: str = "Test Arena", location: str = "Casablanca", **kwargs) -> Venue:
        return self._add(Venue(name=name, location=location, **kwargs))

    def member(self, *, venue: Venue, user: User, role=VenueRole.MANAGER) -> VenueMember:
        return self._add(VenueMember(venue_id=venue.id, user_id=user.id, role=role))

    def field(self, *, venue: Venue, name: str = "Pitch 1") -> Field:
        return self._add(Field(venue_id=venue.id, name=name))

    def camera(self, *, field: Field, name: str = "Cam 1", token: str = "camera-secret") -> Camera:
        from app.services.venue_service import hash_camera_token

        return self._add(Camera(field_id=field.id, name=name, token_hash=hash_camera_token(token)))

    def match(
        self,
        *,
        field: Field,
        starts_in_hours: float = 24,
        duration_minutes: int = 60,
        status=MatchStatus.SCHEDULED,
        join_code: str | None = None,
        title: str | None = "Test match",
    ) -> Match:
        starts_at = dt.datetime.now(dt.UTC) + dt.timedelta(hours=starts_in_hours)
        return self._add(
            Match(
                field_id=field.id,
                starts_at=starts_at,
                ends_at=starts_at + dt.timedelta(minutes=duration_minutes),
                status=status,
                title=title,
                join_code=join_code or generate_join_code(6),
            )
        )

    def player(
        self, *, match: Match, user: User, team=Team.A, jersey_number: int = 7
    ) -> MatchPlayer:
        return self._add(
            MatchPlayer(
                match_id=match.id,
                user_id=user.id,
                team=team,
                jersey_number=jersey_number,
                consent_at=dt.datetime.now(dt.UTC),
            )
        )


@dataclass
class VenueSetup:
    """A venue with a manager, a field and a camera — the usual starting point."""

    venue: Venue
    field: Field
    camera: Camera
    camera_token: str
    manager_phone: str
    admin_phone: str


@pytest.fixture
def venue_setup(factory: Factory) -> VenueSetup:
    factory.user(phone="+212600000900", name="Platform Admin", role=UserRole.ADMIN)
    manager = factory.user(
        phone="+212600000901", name="Arena Manager", role=UserRole.VENUE_OPERATOR
    )
    venue = factory.venue(
        name="Arena Test Casablanca",
        location="Boulevard Zerktouni",
        recording_disclosure="This pitch is recorded.",
    )
    factory.member(venue=venue, user=manager, role=VenueRole.MANAGER)
    field = factory.field(venue=venue, name="Pitch 1")
    camera = factory.camera(field=field, token="camera-secret")
    return VenueSetup(
        venue=venue,
        field=field,
        camera=camera,
        camera_token="camera-secret",
        manager_phone="+212600000901",
        admin_phone="+212600000900",
    )
