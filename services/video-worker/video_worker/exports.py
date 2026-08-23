"""On-demand exports.

The 9:16 crop is generated with the rest of the clips, but a highlight can end up
without one — the vertical pass is allowed to fail without failing the match, and
a venue can turn it off. This regenerates a single one when a player taps share.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from matchly_shared.config import Settings
from matchly_shared.domain import Highlight
from matchly_shared.logging import get_logger
from matchly_shared.storage import ObjectStorage, keys, parse_uri

from . import ffmpeg

logger = get_logger(__name__)


def export_vertical(
    session, *, highlight_id: uuid.UUID, storage: ObjectStorage, settings: Settings
) -> dict:
    highlight = session.get(Highlight, highlight_id)
    if highlight is None:
        return {"status": "not_found", "highlight_id": str(highlight_id)}
    if highlight.video_url_vertical:
        return {"status": "exists", "highlight_id": str(highlight_id)}

    video = highlight.video
    source_uri = (video.processed_url or video.original_url) if video else None
    if not source_uri:
        return {"status": "no_source", "highlight_id": str(highlight_id)}

    ref = parse_uri(source_uri)
    local = storage.local_path(ref.bucket, ref.key)
    source = local or storage.signed_download_url(
        ref.bucket, ref.key, ttl_seconds=settings.signed_url_ttl_seconds
    )

    with tempfile.TemporaryDirectory(prefix="matchly-export-") as tmp:
        output = Path(tmp) / f"{highlight.id}-vertical.mp4"
        ffmpeg.cut_clip(
            source,
            output,
            start=highlight.start_time,
            duration=highlight.end_time - highlight.start_time,
            vertical=True,
        )
        highlight.video_url_vertical = storage.put_file(
            settings.storage_bucket_derived,
            keys.clip_key(video.id, highlight.id, vertical=True),
            output,
            content_type="video/mp4",
        )
    session.commit()
    logger.info("export.vertical_created", extra={"highlight_id": str(highlight_id)})
    return {"status": "created", "highlight_id": str(highlight_id)}
