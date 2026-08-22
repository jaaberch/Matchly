"""Signed media delivery for the local storage backend.

In production, signed URLs point straight at R2/S3 and this router is not mounted.
In development it stands in for the object store so the whole app — private
buckets, expiring links, no public objects — behaves the same way locally.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from matchly_shared.storage import LocalStorage, ObjectNotFound

from ...core.errors import NotFound, PermissionDenied
from ..deps import StorageDep

router = APIRouter(prefix="/media", tags=["media"], include_in_schema=False)


@router.get("/{bucket}/{key:path}")
def get_media(
    bucket: str,
    key: str,
    storage: StorageDep,
    expires: int = Query(...),
    signature: str = Query(...),
) -> FileResponse:
    if not isinstance(storage, LocalStorage):  # pragma: no cover - not mounted in prod
        raise NotFound()
    if not storage.verify_signature(bucket, key, expires, signature):
        raise PermissionDenied("This link is invalid or has expired.")
    try:
        info = storage.stat(bucket, key)
    except ObjectNotFound as exc:
        raise NotFound("That object does not exist.") from exc
    return FileResponse(storage._path(info.bucket, info.key))
