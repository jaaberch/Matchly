"""Recognizer implementations and crop extraction."""

from __future__ import annotations

import re
from pathlib import Path

from matchly_shared.logging import get_logger

from ..tracking import Track
from .base import CropRequest, LoadedCrop, jersey_region

logger = get_logger(__name__)

#: Moments to inspect per track. More reads make a better vote, but each one is a
#: seek into the master; beyond about a dozen the vote stops improving.
CROPS_PER_TRACK = 8

#: Skip crops smaller than this on the master — the number will not be legible
#: and a bad read is worse than none.
MIN_CROP_HEIGHT = 48

_DIGITS = re.compile(r"\d{1,2}")


def choose_moments(track: Track, *, limit: int = CROPS_PER_TRACK) -> list[CropRequest]:
    """Pick the frames most likely to show a readable number.

    Biggest boxes first — a larger box means the player is nearer the camera and
    less occluded — then thinned so the picks are spread across the track rather
    than clustered in one second, since a run of near-identical frames produces
    correlated reads and a falsely confident vote.
    """
    if not track.points:
        return []

    by_size = sorted(track.points, key=lambda point: point.box.area, reverse=True)
    chosen: list = []
    minimum_gap = max(0.5, track.duration / (limit * 2)) if track.duration else 0.0

    for point in by_size:
        if len(chosen) >= limit:
            break
        if any(abs(point.timestamp - taken.timestamp) < minimum_gap for taken in chosen):
            continue
        chosen.append(point)

    chosen.sort(key=lambda point: point.timestamp)
    return [
        CropRequest(track_ref=track.ref, timestamp=point.timestamp, box=point.box)
        for point in chosen
    ]


def extract_crops(
    master: str | Path,
    requests: list[CropRequest],
    *,
    scale: float,
    min_height: int = MIN_CROP_HEIGHT,
) -> list[LoadedCrop]:
    """Seek the master at each moment and cut out the jersey region.

    One seek per request. Decoding the whole master to reach a dozen frames would
    cost more than the rest of the pipeline put together.
    """
    import cv2

    capture = cv2.VideoCapture(str(master))
    if not capture.isOpened():
        logger.warning("jersey.master_unreadable", extra={"master": str(master)})
        return []

    crops: list[LoadedCrop] = []
    try:
        for request in requests:
            capture.set(cv2.CAP_PROP_POS_MSEC, request.timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue

            height, width = frame.shape[:2]
            region = jersey_region(request.box, scale=scale)
            x1 = max(0, int(region.x1))
            y1 = max(0, int(region.y1))
            x2 = min(width, int(region.x2))
            y2 = min(height, int(region.y2))
            if x2 - x1 < 8 or y2 - y1 < min_height:
                continue

            crops.append(
                LoadedCrop(
                    track_ref=request.track_ref,
                    timestamp=request.timestamp,
                    image=frame[y1:y2, x1:x2].copy(),
                )
            )
    finally:
        capture.release()

    logger.info(
        "jersey.crops_extracted",
        extra={"requested": len(requests), "usable": len(crops)},
    )
    return crops


class NullJerseyRecognizer:
    """Reads nothing, and says so.

    The fallback when no OCR runtime is installed. Every track then goes
    unattributed and highlights are delivered as general match moments — which is
    the documented behaviour when jersey recognition is unavailable, not an error.
    """

    name = "null"

    def read(self, crops: list[LoadedCrop]) -> list[tuple[str, int, float]]:
        return []


class EasyOcrJerseyRecognizer:
    """General-purpose OCR, constrained to digits.

    Not a jersey model — it is a text reader pointed at a shirt, and it reads
    creased fabric at an angle about as well as that suggests. It earns its place
    only because the temporal vote is sceptical: individually poor reads across a
    whole track still converge, and the vote refuses to answer when they do not.

    A digit classifier trained on crops from these pitches would be markedly
    better, and the footage to train one is what running this produces.
    """

    name = "easyocr"

    def __init__(self, *, languages: tuple[str, ...] = ("en",)) -> None:
        self._languages = list(languages)
        self._reader = None

    def _get_reader(self):
        if self._reader is None:
            import easyocr

            self._reader = easyocr.Reader(self._languages, gpu=False, verbose=False)
        return self._reader

    def read(self, crops: list[LoadedCrop]) -> list[tuple[str, int, float]]:
        if not crops:
            return []
        reader = self._get_reader()

        readings: list[tuple[str, int, float]] = []
        for crop in crops:
            try:
                # allowlist keeps it from reading a sponsor's name as a number.
                results = reader.readtext(crop.image, allowlist="0123456789", detail=1)
            except Exception as exc:  # a single unreadable crop is not fatal
                logger.debug("jersey.read_failed", extra={"error": str(exc)[:120]})
                continue
            for _, text, confidence in results:
                match = _DIGITS.search(text or "")
                if not match:
                    continue
                number = int(match.group())
                if 0 <= number <= 99:
                    readings.append((crop.track_ref, number, float(confidence)))
        return readings


def build_recognizer() -> JerseyRecognizerProtocol:
    """The best recognizer this worker can offer.

    Never raises: an absent OCR runtime is an expected deployment, not a fault.
    """
    try:
        import easyocr  # noqa: F401

        return EasyOcrJerseyRecognizer()
    except ImportError:
        logger.info("jersey.no_ocr_runtime", extra={"recognizer": "null"})
        return NullJerseyRecognizer()


# Imported late to avoid a circular import at module load.
from .base import JerseyRecognizer as JerseyRecognizerProtocol  # noqa: E402
