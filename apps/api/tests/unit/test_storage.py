"""Local storage backend and the storage contract.

These tests cover the behaviour the pipeline depends on: overwrite-on-retry,
prefix deletion for match/retention purges, and signed URLs that actually expire
and cannot be forged.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from matchly_shared.storage import LocalStorage, ObjectNotFound, keys, parse_uri

BUCKET = "matchly-derived"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path, signing_key="unit-test-signing-key")


def test_put_and_get_round_trip(storage: LocalStorage) -> None:
    uri = storage.put_bytes(BUCKET, "videos/v1/clip.mp4", b"payload")

    assert uri == f"file://{BUCKET}/videos/v1/clip.mp4"
    assert storage.get_bytes(BUCKET, "videos/v1/clip.mp4") == b"payload"
    assert storage.exists(BUCKET, "videos/v1/clip.mp4")


def test_writes_overwrite_so_retried_steps_are_idempotent(storage: LocalStorage) -> None:
    storage.put_bytes(BUCKET, "videos/v1/clip.mp4", b"first attempt")
    storage.put_bytes(BUCKET, "videos/v1/clip.mp4", b"second attempt")

    assert storage.get_bytes(BUCKET, "videos/v1/clip.mp4") == b"second attempt"
    assert len(list(storage.list(BUCKET))) == 1


def test_missing_object_raises(storage: LocalStorage) -> None:
    assert storage.exists(BUCKET, "nope.mp4") is False
    with pytest.raises(ObjectNotFound):
        storage.get_bytes(BUCKET, "nope.mp4")


def test_delete_is_forgiving(storage: LocalStorage) -> None:
    # Deleting an object that is already gone must not fail a retried cleanup job.
    storage.delete(BUCKET, "never-existed.mp4")


def test_delete_prefix_removes_a_whole_video(storage: LocalStorage) -> None:
    for index in range(3):
        storage.put_bytes(BUCKET, keys.clip_key("v1", f"h{index}"), b"clip")
    storage.put_bytes(BUCKET, keys.clip_key("v2", "other"), b"keep me")

    removed = storage.delete_prefix(BUCKET, keys.video_derived_prefix("v1"))

    assert removed == 3
    assert storage.exists(BUCKET, keys.clip_key("v2", "other"))


def test_total_size_reports_usage(storage: LocalStorage) -> None:
    storage.put_bytes(BUCKET, "a.bin", b"1234")
    storage.put_bytes(BUCKET, "b.bin", b"12345678")

    assert storage.total_size(BUCKET) == 12


def test_put_file_and_download(storage: LocalStorage, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video bytes")

    storage.put_file(BUCKET, "videos/v1/replay.mp4", source)
    downloaded = storage.download(BUCKET, "videos/v1/replay.mp4", tmp_path / "out" / "r.mp4")

    assert downloaded.read_bytes() == b"video bytes"


def test_signed_url_verifies(storage: LocalStorage) -> None:
    url = storage.signed_download_url(BUCKET, "videos/v1/clip.mp4", ttl_seconds=60)
    expires = int(url.split("expires=")[1].split("&")[0])
    signature = url.split("signature=")[1]

    assert storage.verify_signature(BUCKET, "videos/v1/clip.mp4", expires, signature)


def test_signature_cannot_be_replayed_for_another_object(storage: LocalStorage) -> None:
    url = storage.signed_download_url(BUCKET, "videos/v1/private.mp4", ttl_seconds=60)
    expires = int(url.split("expires=")[1].split("&")[0])
    signature = url.split("signature=")[1]

    # Same signature, different key: one player must not reach another's video.
    assert not storage.verify_signature(BUCKET, "videos/v2/private.mp4", expires, signature)


def test_expired_signature_is_rejected(storage: LocalStorage) -> None:
    expires = int(time.time()) - 1
    signature = storage._sign(BUCKET, "videos/v1/clip.mp4", expires, "GET")

    assert not storage.verify_signature(BUCKET, "videos/v1/clip.mp4", expires, signature)


def test_forged_signature_is_rejected(storage: LocalStorage) -> None:
    expires = int(time.time()) + 60

    assert not storage.verify_signature(BUCKET, "videos/v1/clip.mp4", expires, "forged")


@pytest.mark.parametrize("key", ["../escape.txt", "a/../../escape.txt"])
def test_keys_cannot_escape_the_bucket(storage: LocalStorage, key: str) -> None:
    with pytest.raises(ValueError):
        storage.put_bytes(BUCKET, key, b"nope")


def test_uri_parsing_is_backend_agnostic() -> None:
    # A row written under the local backend must still resolve when running on S3.
    for uri in (
        "s3://matchly-derived/videos/v1/clip.mp4",
        "file://matchly-derived/videos/v1/clip.mp4",
        "matchly-derived/videos/v1/clip.mp4",
    ):
        ref = parse_uri(uri)
        assert ref.bucket == "matchly-derived"
        assert ref.key == "videos/v1/clip.mp4"


@pytest.mark.parametrize("bad", ["", "no-slash", "s3://bucket-only"])
def test_bad_uris_raise(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_uri(bad)


def test_signed_url_for_uri_tolerates_none(storage: LocalStorage) -> None:
    assert storage.signed_url_for_uri(None, ttl_seconds=60) is None


def test_object_keys_are_deterministic() -> None:
    # Determinism is what makes CUT_CLIPS idempotent across retries.
    assert keys.clip_key("v1", "h1") == keys.clip_key("v1", "h1")
    assert keys.clip_key("v1", "h1", vertical=True).endswith("-vertical.mp4")
    assert keys.master_key("m1", "v1").startswith("matches/m1/")
