"""Database engine and session management.

Shared because the workers persist their own results (video metadata, tracks,
highlights, job state) against the same schema. Migrations remain owned solely by
``apps/api/alembic``.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_settings


def build_engine(settings: Settings) -> Engine:
    kwargs: dict[str, object] = {
        "echo": settings.database_echo,
        "future": True,
        # Long-running workers outlive idle timeouts on managed Postgres.
        "pool_pre_ping": True,
    }
    if settings.database_url.startswith("sqlite"):
        # SQLite is only used by the unit tests.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = settings.database_pool_size
        kwargs["max_overflow"] = settings.database_max_overflow
        kwargs["pool_recycle"] = 1800
    return create_engine(settings.database_url, **kwargs)


@functools.lru_cache(maxsize=1)
def get_engine() -> Engine:
    return build_engine(get_settings())


@functools.lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for worker code: commit on success, roll back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_cache() -> None:
    """Drop cached engine/session factory. Tests call this after changing settings."""
    get_engine.cache_clear()
    get_session_factory.cache_clear()
