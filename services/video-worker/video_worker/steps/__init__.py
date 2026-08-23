"""Pipeline step implementations.

Importing this package registers every step this worker can run, and the
detectors it can offer. The runner then executes whatever is registered and
leaves the rest PENDING for another worker — which is how the computer-vision
steps move to a GPU node without touching the orchestration.
"""

# Registers the motion and mock detectors. Without this the ladder is empty and
# SCORE_EVENTS has nothing to ask, which fails a match rather than degrading it.
from .. import highlights as detectors  # noqa: F401
from . import highlights, ingest, media  # noqa: F401  (imported for registration)

__all__ = ["detectors", "highlights", "ingest", "media"]
