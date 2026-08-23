"""Pipeline step implementations.

Importing this package registers every step this worker can run. The runner then
executes whatever is registered and leaves the rest PENDING for another worker —
which is how the CV steps will move to a GPU node in Phase 5 without touching the
orchestration.
"""

from . import highlights, ingest, media  # noqa: F401  (imported for registration)

__all__ = ["highlights", "ingest", "media"]
