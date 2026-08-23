"""Object storage abstraction.

Matchly never talks to a cloud SDK directly. Everything goes through
:class:`ObjectStorage`, which has a filesystem implementation for development and
tests and an S3-compatible implementation that serves both AWS S3 and Cloudflare R2.

Stored references are URIs of the form ``{scheme}://{bucket}/{key}``. Parsing is
scheme-agnostic on purpose: a row written while running on the local backend still
resolves against S3 as long as the bucket name matches, so moving between vendors
is a configuration change, not a data migration.
"""

from __future__ import annotations

import abc
import dataclasses
import datetime as dt
from collections.abc import Iterator
from pathlib import Path


class StorageError(RuntimeError):
    """Raised for any storage-layer failure the caller is expected to handle."""


class ObjectNotFound(StorageError):
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class ObjectRef:
    bucket: str
    key: str

    @property
    def uri(self) -> str:
        return f"{self.bucket}/{self.key}"


@dataclasses.dataclass(frozen=True, slots=True)
class ObjectInfo:
    bucket: str
    key: str
    size: int
    content_type: str | None = None
    last_modified: dt.datetime | None = None


def parse_uri(uri: str) -> ObjectRef:
    """Split ``scheme://bucket/key`` into its parts.

    The scheme is ignored deliberately (see module docstring). A bare
    ``bucket/key`` string is also accepted.
    """
    remainder = uri.split("://", 1)[1] if "://" in uri else uri
    bucket, sep, key = remainder.partition("/")
    if not bucket or not sep or not key:
        raise ValueError(f"Not a storage URI: {uri!r}")
    return ObjectRef(bucket=bucket, key=key)


class ObjectStorage(abc.ABC):
    """Minimal surface the platform needs. Keep it small; add only what is used."""

    #: URI scheme this backend writes.
    scheme: str = "storage"

    def uri(self, bucket: str, key: str) -> str:
        return f"{self.scheme}://{bucket}/{key}"

    # ── writes ───────────────────────────────────────────────────────────
    @abc.abstractmethod
    def put_bytes(
        self, bucket: str, key: str, data: bytes, *, content_type: str | None = None
    ) -> str:
        """Write bytes; return the stored URI. Overwrites, so retries are idempotent."""

    @abc.abstractmethod
    def put_file(
        self, bucket: str, key: str, path: str | Path, *, content_type: str | None = None
    ) -> str:
        """Upload a local file; return the stored URI."""

    # ── reads ────────────────────────────────────────────────────────────
    @abc.abstractmethod
    def get_bytes(self, bucket: str, key: str) -> bytes: ...

    @abc.abstractmethod
    def download(self, bucket: str, key: str, dest: str | Path) -> Path:
        """Fetch an object to a local path; return that path."""

    @abc.abstractmethod
    def exists(self, bucket: str, key: str) -> bool: ...

    @abc.abstractmethod
    def stat(self, bucket: str, key: str) -> ObjectInfo: ...

    @abc.abstractmethod
    def list(self, bucket: str, prefix: str = "") -> Iterator[ObjectInfo]: ...

    # ── deletes ──────────────────────────────────────────────────────────
    @abc.abstractmethod
    def delete(self, bucket: str, key: str) -> None:
        """Delete one object. Deleting a missing object is not an error."""

    @abc.abstractmethod
    def delete_prefix(self, bucket: str, prefix: str) -> int:
        """Delete everything under a prefix; return how many objects went. Used by
        match deletion and the retention purge."""

    # ── signing ──────────────────────────────────────────────────────────
    @abc.abstractmethod
    def signed_download_url(self, bucket: str, key: str, *, ttl_seconds: int) -> str:
        """Short-lived read URL. Buckets stay private; this is the only way in."""

    @abc.abstractmethod
    def signed_upload_url(
        self, bucket: str, key: str, *, ttl_seconds: int, content_type: str | None = None
    ) -> str:
        """Short-lived PUT target so large recordings never pass through the API."""

    # ── convenience ──────────────────────────────────────────────────────
    def local_path(self, bucket: str, key: str) -> Path | None:
        """Filesystem path for an object, when there is one.

        ffmpeg can read either a path or an HTTP URL. Returning a path where one
        exists avoids copying a 30 GB master just to read its header; the
        S3-backed implementation returns ``None`` and callers fall back to a
        signed URL.
        """
        return None

    def signed_url_for_uri(self, uri: str | None, *, ttl_seconds: int) -> str | None:
        """Resolve a stored URI to a signed link, tolerating ``None``."""
        if not uri:
            return None
        ref = parse_uri(uri)
        return self.signed_download_url(ref.bucket, ref.key, ttl_seconds=ttl_seconds)

    def total_size(self, bucket: str, prefix: str = "") -> int:
        """Bytes stored under a prefix. Backs the admin storage-usage view."""
        return sum(info.size for info in self.list(bucket, prefix))
