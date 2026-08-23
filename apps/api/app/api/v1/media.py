"""Signed media delivery for the local storage backend.

In production, signed URLs point straight at R2/S3 and this router is not mounted.
In development it stands in for the object store so the whole app — private
buckets, expiring links, no public objects — behaves the same way locally.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response, status
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
    path = storage.local_path(info.bucket, info.key)
    if path is None:  # pragma: no cover - only reachable if the file vanished
        raise NotFound("That object does not exist.")
    return FileResponse(path)


@router.put("/{bucket}/{key:path}", status_code=status.HTTP_200_OK)
async def put_media(
    bucket: str,
    key: str,
    request: Request,
    storage: StorageDep,
    expires: int = Query(...),
    signature: str = Query(...),
) -> Response:
    """Accept a presigned upload in development.

    In production this URL points at R2 or S3 and this handler does not exist.
    Locally it stands in for the object store so the upload path under test is
    the same one the capture agent will use.
    """
    if not isinstance(storage, LocalStorage):  # pragma: no cover - not mounted in prod
        raise NotFound()
    if not storage.verify_signature(bucket, key, expires, signature, method="PUT"):
        raise PermissionDenied("This upload link is invalid or has expired.")

    body = await request.body()
    storage.put_bytes(bucket, key, body)
    return Response(status_code=status.HTTP_200_OK)
