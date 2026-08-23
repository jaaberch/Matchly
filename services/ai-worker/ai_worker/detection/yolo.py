"""YOLO player detection.

A pretrained COCO model, restricted to the ``person`` class. Football-specific
models exist and would be better, but they need labelled footage from these
pitches — which is exactly what running this in production will produce.

The model is loaded once per process and lazily: importing this module must not
pull torch into memory, because the media worker imports the package to see
whether CV is available at all.
"""

from __future__ import annotations

import functools
from pathlib import Path

from matchly_shared.logging import get_logger

from .base import Box, FrameDetections, PlayerDetector

logger = get_logger(__name__)

#: COCO class 0. The pitch also contains a ball, a referee and spectators; only
#: people are useful for the density and clustering signals.
PERSON_CLASS = 0

#: Below this, a "player" on a wide 4K shot is usually a shadow or a line marking.
DEFAULT_CONFIDENCE = 0.25

#: Nano is the right trade for a 640p proxy on CPU: a larger model costs several
#: times the runtime for detections that the density signal cannot tell apart.
DEFAULT_MODEL = "yolov8n.pt"


class ModelUnavailable(RuntimeError):
    """The CV runtime or the weights are missing. Callers must degrade, not crash."""


@functools.lru_cache(maxsize=2)
def _load_model(weights: str):
    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - depends on the image
        raise ModelUnavailable(
            "ultralytics is not installed in this worker. Detection is optional: "
            "the match will still be delivered with motion-based highlights."
        ) from exc
    try:
        return YOLO(weights)
    except Exception as exc:  # weights missing, corrupt, or undownloadable
        raise ModelUnavailable(f"could not load {weights}: {exc}") from exc


class YoloPlayerDetector(PlayerDetector):
    def __init__(
        self,
        *,
        weights: str = DEFAULT_MODEL,
        confidence: float = DEFAULT_CONFIDENCE,
        image_size: int = 640,
        batch_size: int = 16,
    ) -> None:
        self.weights = weights
        self.confidence = confidence
        self.image_size = image_size
        self.batch_size = batch_size
        self.name = f"yolo:{Path(weights).stem}"

    def detect(self, frames: list[Path], *, fps: float) -> list[FrameDetections]:
        if not frames:
            return []
        model = _load_model(self.weights)

        results: list[FrameDetections] = []
        for start in range(0, len(frames), self.batch_size):
            batch = frames[start : start + self.batch_size]
            predictions = model.predict(
                [str(path) for path in batch],
                classes=[PERSON_CLASS],
                conf=self.confidence,
                imgsz=self.image_size,
                verbose=False,
            )
            for offset, prediction in enumerate(predictions):
                index = start + offset
                results.append(
                    FrameDetections(
                        frame_index=index,
                        timestamp=index / max(fps, 0.01),
                        boxes=_boxes_from(prediction),
                    )
                )

        total = sum(item.count for item in results)
        logger.info(
            "detection.completed",
            extra={
                "frames": len(frames),
                "detections": total,
                "mean_per_frame": round(total / max(len(frames), 1), 1),
            },
        )
        return results


def _boxes_from(prediction) -> list[Box]:
    boxes = getattr(prediction, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []
    coordinates = boxes.xyxy.tolist()
    confidences = boxes.conf.tolist()
    return [
        Box(x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2), confidence=float(score))
        for (x1, y1, x2, y2), score in zip(coordinates, confidences, strict=False)
    ]


def available(weights: str = DEFAULT_MODEL) -> bool:
    """Whether this worker can actually detect. Never raises."""
    try:
        _load_model(weights)
        return True
    except Exception:
        return False
