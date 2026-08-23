"""Getting at the recording without copying 30 GB around.

ffmpeg reads local paths and HTTP URLs equally well, so a step asks for whichever
is cheaper: the file itself when storage is on disk, a short-lived signed URL
when it is in R2 or S3. Only when a step genuinely needs the bytes locally — such
as joining segments — is anything downloaded.
"""

from __future__ import annotations

from pathlib import Path

from matchly_shared.pipeline import StepContext, StepError
from matchly_shared.storage import ObjectNotFound, parse_uri


def readable(context: StepContext, uri: str | None) -> str | Path:
    """A path or URL ffmpeg can open for ``uri``."""
    if not uri:
        raise StepError("nothing to read: this video has no stored object")
    ref = parse_uri(uri)

    local = context.storage.local_path(ref.bucket, ref.key)
    if local is not None:
        return local

    if not context.storage.exists(ref.bucket, ref.key):
        raise ObjectNotFound(f"{ref.bucket}/{ref.key}")
    return context.storage.signed_download_url(
        ref.bucket, ref.key, ttl_seconds=context.settings.signed_url_ttl_seconds
    )


def download(context: StepContext, uri: str, destination: Path) -> Path:
    ref = parse_uri(uri)
    return context.storage.download(ref.bucket, ref.key, destination)


def master_source(context: StepContext) -> str | Path:
    """The joined recording. VALIDATE guarantees ``original_url`` is set."""
    return readable(context, context.video.original_url)


def proxy_source(context: StepContext) -> str | Path:
    """The low-resolution copy the CV steps read."""
    return readable(context, context.video.proxy_url)
