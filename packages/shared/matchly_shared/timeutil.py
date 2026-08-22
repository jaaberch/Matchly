"""UTC time helpers.

Every timestamp in Matchly is UTC. PostgreSQL's ``timestamptz`` hands back
timezone-aware datetimes, but SQLite (used by the fast unit-test path) returns
naive ones, and mixing the two raises ``TypeError`` on the first subtraction.
:func:`ensure_utc` is the single place that reconciles them.
"""

from __future__ import annotations

import datetime as dt


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def ensure_utc(value: dt.datetime | None) -> dt.datetime | None:
    """Attach UTC to a naive datetime read back from the database."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
