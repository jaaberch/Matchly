"""Vendor-neutral object storage (Cloudflare R2, AWS S3, MinIO, local disk)."""

from . import keys
from .base import (
    ObjectInfo,
    ObjectNotFound,
    ObjectRef,
    ObjectStorage,
    StorageError,
    parse_uri,
)
from .factory import build_storage, get_storage
from .local import LocalStorage
from .s3 import S3CompatibleStorage

__all__ = [
    "LocalStorage",
    "ObjectInfo",
    "ObjectNotFound",
    "ObjectRef",
    "ObjectStorage",
    "S3CompatibleStorage",
    "StorageError",
    "build_storage",
    "get_storage",
    "keys",
    "parse_uri",
]
