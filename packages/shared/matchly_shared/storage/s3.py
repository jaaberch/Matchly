"""S3-compatible storage: AWS S3, Cloudflare R2 and MinIO.

The same class serves all three. R2 is the default target for production because
it has no egress fees, which matters a great deal when the product is people
repeatedly watching and sharing video. Nothing above this module knows which one
is in use.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .base import ObjectInfo, ObjectNotFound, ObjectStorage, StorageError


class S3CompatibleStorage(ObjectStorage):
    scheme = "s3"

    def __init__(
        self,
        *,
        endpoint_url: str | None = None,
        region: str = "auto",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        force_path_style: bool = True,
        client: Any | None = None,
    ) -> None:
        if client is not None:
            self._client = client
            return
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise StorageError(
                "boto3 is required for STORAGE_BACKEND=s3 (install matchly-shared[s3])"
            ) from exc

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if force_path_style else "auto"},
                retries={"max_attempts": 5, "mode": "standard"},
            ),
        )

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _guess_type(key: str, content_type: str | None) -> str:
        return content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"

    def _is_missing(self, exc: Exception) -> bool:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        return code in ("404", "NoSuchKey", "NotFound")

    # ── writes ───────────────────────────────────────────────────────────
    def put_bytes(
        self, bucket: str, key: str, data: bytes, *, content_type: str | None = None
    ) -> str:
        self._client.put_object(
            Bucket=bucket, Key=key, Body=data, ContentType=self._guess_type(key, content_type)
        )
        return self.uri(bucket, key)

    def put_file(
        self, bucket: str, key: str, path: str | Path, *, content_type: str | None = None
    ) -> str:
        source = Path(path)
        if not source.is_file():
            raise ObjectNotFound(f"No such local file: {source}")
        # upload_file does multipart automatically, which a 30 GB master needs.
        self._client.upload_file(
            str(source),
            bucket,
            key,
            ExtraArgs={"ContentType": self._guess_type(key, content_type)},
        )
        return self.uri(bucket, key)

    # ── reads ────────────────────────────────────────────────────────────
    def get_bytes(self, bucket: str, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as exc:
            if self._is_missing(exc):
                raise ObjectNotFound(f"{bucket}/{key}") from exc
            raise

    def download(self, bucket: str, key: str, dest: str | Path) -> Path:
        destination = Path(dest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(bucket, key, str(destination))
        except Exception as exc:
            if self._is_missing(exc):
                raise ObjectNotFound(f"{bucket}/{key}") from exc
            raise
        return destination

    def exists(self, bucket: str, key: str) -> bool:
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception as exc:
            if self._is_missing(exc):
                return False
            raise

    def stat(self, bucket: str, key: str) -> ObjectInfo:
        try:
            head = self._client.head_object(Bucket=bucket, Key=key)
        except Exception as exc:
            if self._is_missing(exc):
                raise ObjectNotFound(f"{bucket}/{key}") from exc
            raise
        return ObjectInfo(
            bucket=bucket,
            key=key,
            size=int(head.get("ContentLength", 0)),
            content_type=head.get("ContentType"),
            last_modified=head.get("LastModified"),
        )

    def list(self, bucket: str, prefix: str = "") -> Iterator[ObjectInfo]:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                yield ObjectInfo(
                    bucket=bucket,
                    key=item["Key"],
                    size=int(item.get("Size", 0)),
                    last_modified=item.get("LastModified"),
                )

    # ── deletes ──────────────────────────────────────────────────────────
    def delete(self, bucket: str, key: str) -> None:
        self._client.delete_object(Bucket=bucket, Key=key)

    def delete_prefix(self, bucket: str, prefix: str) -> int:
        deleted = 0
        batch: list[dict[str, str]] = []
        for info in self.list(bucket, prefix):
            batch.append({"Key": info.key})
            if len(batch) == 1000:  # S3 delete_objects hard limit
                self._client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
                deleted += len(batch)
                batch = []
        if batch:
            self._client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
            deleted += len(batch)
        return deleted

    # ── signing ──────────────────────────────────────────────────────────
    def signed_download_url(self, bucket: str, key: str, *, ttl_seconds: int) -> str:
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=ttl_seconds
        )

    def signed_upload_url(
        self, bucket: str, key: str, *, ttl_seconds: int, content_type: str | None = None
    ) -> str:
        params: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        return self._client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=ttl_seconds
        )
