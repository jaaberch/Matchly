"""FastAPI database dependency.

One session per request, committed by the route on success and rolled back on any
raised exception.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from matchly_shared.db import get_session_factory


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
