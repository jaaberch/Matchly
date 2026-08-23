"""Step input fingerprints.

A step that already succeeded is skipped on a re-run — unless its inputs changed.
The fingerprint is what tells those two cases apart, so a re-uploaded recording
re-probes and re-transcodes while an unchanged one does not pay for it twice.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def fingerprint(*parts: Any) -> str:
    """Stable hash of a step's inputs. Order matters; ``None`` is significant."""
    payload = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:32]
