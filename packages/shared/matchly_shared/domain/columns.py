"""Portable column type decorators.

PostgreSQL is the production database. Unit tests run against SQLite so they need
no server, so UUID and JSON columns are declared through these decorators rather
than the postgres-only types directly.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CHAR, JSON, TypeDecorator
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect


class GUID(TypeDecorator):
    """UUID column: native ``uuid`` on PostgreSQL, ``CHAR(36)`` elsewhere."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


#: JSONB on PostgreSQL (indexable), plain JSON elsewhere.
JSONBType = JSON().with_variant(postgresql.JSONB(astext_type=postgresql.TEXT()), "postgresql")


def new_uuid() -> uuid.UUID:
    """Application-side id generation.

    Ids are generated before insert so a worker can build deterministic object
    storage keys (``{video_id}/clips/{highlight_id}.mp4``) in the same transaction
    that writes the row.
    """
    return uuid.uuid4()
