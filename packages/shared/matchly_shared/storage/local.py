"""Filesystem-backed storage for development and tests.

Signed URLs are simulated: the "signature" is an HMAC over bucket/key/expiry, which
the API's ``/media`` route verifies. It behaves like a real signed URL (expires,
cannot be forged, is the only way to read a private object) without needing MinIO.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from .base import ObjectInfo, ObjectNotFound, ObjectStorage


class LocalStorage(ObjectStorage):
    scheme = "file"

    def __init__(
        self,
        root: str | Path,
        *,
        signing_key: str,
        public_base_url: str = "http://localhost:8000/media",
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._signing_key = signing_key.encode()
        self._public_base_url = public_base_url.rstrip("/")

    # ── paths ────────────────────────────────────────────────────────────
    def _path(self, bucket: str, key: str) -> Path:
        if not bucket or ".." in bucket:
            raise ValueError(f"Invalid bucket: {bucket!r}")
        candidate = (self.root / bucket / key).resolve()
        bucket_root = (self.root / bucket).resolve()
        # Refuse keys that would escape the bucket directory.
        if not candidate.is_relative_to(bucket_root):
            raise ValueError(f"Invalid key: {key!r}")
        return candidate

    # ── writes ───────────────────────────────────────────────────────────
    def put_bytes(
        self, bucket: str, key: str, data: bytes, *, content_type: str | None = None
    ) -> str:
        path = self._path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.uri(bucket, key)

    def put_file(
        self, bucket: str, key: str, path: str | Path, *, content_type: str | None = None
    ) -> str:
        source = Path(path)
        if not source.is_file():
            raise ObjectNotFound(f"No such local file: {source}")
        destination = self._path(bucket, key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return self.uri(bucket, key)

    # ── reads ────────────────────────────────────────────────────────────
    def get_bytes(self, bucket: str, key: str) -> bytes:
        path = self._path(bucket, key)
        if not path.is_file():
            raise ObjectNotFound(f"{bucket}/{key}")
        return path.read_bytes()

    def download(self, bucket: str, key: str, dest: str | Path) -> Path:
        destination = Path(dest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self._path(bucket, key)
        if not source.is_file():
            raise ObjectNotFound(f"{bucket}/{key}")
        shutil.copyfile(source, destination)
        return destination

    def exists(self, bucket: str, key: str) -> bool:
        return self._path(bucket, key).is_file()

    def local_path(self, bucket: str, key: str) -> Path | None:
        path = self._path(bucket, key)
        return path if path.is_file() else None

    def stat(self, bucket: str, key: str) -> ObjectInfo:
        path = self._path(bucket, key)
        if not path.is_file():
            raise ObjectNotFound(f"{bucket}/{key}")
        stat = path.stat()
        return ObjectInfo(
            bucket=bucket,
            key=key,
            size=stat.st_size,
            last_modified=dt.datetime.fromtimestamp(stat.st_mtime, dt.UTC),
        )

    def list(self, bucket: str, prefix: str = "") -> Iterator[ObjectInfo]:
        bucket_root = (self.root / bucket).resolve()
        if not bucket_root.is_dir():
            return
        for path in sorted(bucket_root.rglob("*")):
            if not path.is_file():
                continue
            key = path.relative_to(bucket_root).as_posix()
            if key.startswith(prefix):
                stat = path.stat()
                yield ObjectInfo(
                    bucket=bucket,
                    key=key,
                    size=stat.st_size,
                    last_modified=dt.datetime.fromtimestamp(stat.st_mtime, dt.UTC),
                )

    # ── deletes ──────────────────────────────────────────────────────────
    def delete(self, bucket: str, key: str) -> None:
        self._path(bucket, key).unlink(missing_ok=True)

    def delete_prefix(self, bucket: str, prefix: str) -> int:
        deleted = 0
        for info in list(self.list(bucket, prefix)):
            self.delete(bucket, info.key)
            deleted += 1
        return deleted

    # ── signing ──────────────────────────────────────────────────────────
    def _sign(self, bucket: str, key: str, expires: int, method: str) -> str:
        message = f"{method}:{bucket}:{key}:{expires}".encode()
        digest = hmac.new(self._signing_key, message, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def verify_signature(
        self, bucket: str, key: str, expires: int, signature: str, method: str = "GET"
    ) -> bool:
        if expires < int(time.time()):
            return False
        return hmac.compare_digest(self._sign(bucket, key, expires, method), signature)

    def _signed_url(self, bucket: str, key: str, ttl_seconds: int, method: str) -> str:
        expires = int(time.time()) + ttl_seconds
        signature = self._sign(bucket, key, expires, method)
        return (
            f"{self._public_base_url}/{quote(bucket)}/{quote(key)}"
            f"?expires={expires}&signature={signature}"
        )

    def signed_download_url(self, bucket: str, key: str, *, ttl_seconds: int) -> str:
        return self._signed_url(bucket, key, ttl_seconds, "GET")

    def signed_upload_url(
        self, bucket: str, key: str, *, ttl_seconds: int, content_type: str | None = None
    ) -> str:
        return self._signed_url(bucket, key, ttl_seconds, "PUT")
