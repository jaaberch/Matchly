"""Storage backend selection. One place decides which implementation is live."""

from __future__ import annotations

import functools

from ..config import Settings, get_settings
from .base import ObjectStorage
from .local import LocalStorage
from .s3 import S3CompatibleStorage


def build_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend == "s3":
        return S3CompatibleStorage(
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            force_path_style=settings.s3_force_path_style,
        )
    return LocalStorage(
        settings.storage_local_path,
        signing_key=settings.jwt_secret_key,
        public_base_url=f"{settings.api_base_url.rstrip('/')}/media",
    )


@functools.lru_cache(maxsize=1)
def get_storage() -> ObjectStorage:
    """Process-wide storage singleton. Call `.cache_clear()` in tests."""
    return build_storage(get_settings())
