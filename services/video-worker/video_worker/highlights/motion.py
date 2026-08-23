"""Motion-based detection: the fallback that actually watches the recording.

No player detection, no tracking, no model file. It measures how much the picture
changes between sampled frames and calls the busiest moments interesting. On a
fixed wide camera pointed at a pitch that correlates surprisingly well with play:
a still frame is a goal kick or a stoppage, a churning one is a counter-attack.

It is not good enough to be the product. It is good enough that a venue whose CV
worker is down still gets watchable clips, which is the whole point of the
ladder.
"""

from __future__ import annotations

import statistics
from pathlib import Path

from matchly_shared.domain import HighlightType
from matchly_shared.highlights import (
    Candidate,
    DetectionRequest,
    HighlightDetector,
    register_detector,
)
from matchly_shared.logging import get_logger

logger = get_logger(__name__)

#: Sample this far apart when reading the proxy directly, in seconds. Fine enough
#: to catch a break, coarse enough that an hour costs seconds.
SAMPLE_INTERVAL = 1.0

#: A moment must beat the match's own baseline by this much to be a candidate,
#: measured in standard deviations. Absolute thresholds do not transfer between
#: a floodlit pitch at night and a bright afternoon.
MIN_Z_SCORE = 0.6


class MotionHighlightDetector(HighlightDetector):
    name = "motion-v1"

    def detect(self, request: DetectionRequest) -> list[Candidate]:
        series = self._motion_series(request)
        if len(series) < 4:
            return []

        values = [value for _, value in series]
        baseline = statistics.median(values)
        spread = statistics.pstdev(values) or 1e-6

        candidates: list[Candidate] = []
        for timestamp, value in series:
            z_score = (value - baseline) / spread
            if z_score < MIN_Z_SCORE:
                continue
            # Squash to 0..1 without a hard ceiling: 3 sigma reads as ~0.95.
            motion = min(0.99, round(0.5 + z_score / 6, 2))
            candidates.append(
                Candidate(
                    timestamp=round(timestamp, 2),
                    score=motion,
                    signals={"motion": motion},
                    type=HighlightType.HIGH_INTENSITY,
                )
            )

        logger.info(
            "highlights.motion_scored",
            extra={"samples": len(series), "candidates": len(candidates)},
        )
        return candidates

    # ── signal ───────────────────────────────────────────────────────────
    def _motion_series(self, request: DetectionRequest) -> list[tuple[float, float]]:
        """Mean absolute frame difference over time."""
        if request.frames:
            return self._from_frames(request.frames, request.frame_fps)
        if request.proxy_path is not None:
            return self._from_video(request.proxy_path)
        return []

    @staticmethod
    def _read_grey(path: Path):
        import cv2

        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        return None if image is None else cv2.resize(image, (160, 90))

    def _from_frames(self, frames: list[Path], fps: float) -> list[tuple[float, float]]:
        import numpy as np

        series: list[tuple[float, float]] = []
        previous = None
        for index, frame in enumerate(frames):
            current = self._read_grey(frame)
            if current is None:
                continue
            if previous is not None:
                delta = float(np.mean(np.abs(current.astype("int16") - previous.astype("int16"))))
                series.append((index / max(fps, 0.01), delta))
            previous = current
        return series

    def _from_video(self, path: Path) -> list[tuple[float, float]]:
        import cv2
        import numpy as np

        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            return []
        try:
            fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
            stride = max(1, int(round(fps * SAMPLE_INTERVAL)))
            series: list[tuple[float, float]] = []
            previous = None
            index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if index % stride == 0:
                    grey = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90))
                    if previous is not None:
                        delta = float(
                            np.mean(np.abs(grey.astype("int16") - previous.astype("int16")))
                        )
                        series.append((index / fps, delta))
                    previous = grey
                index += 1
            return series
        finally:
            capture.release()


def _supports_motion(request: DetectionRequest) -> bool:
    """Needs pixels: either sampled frames or the proxy itself."""
    return bool(request.frames) or request.proxy_path is not None


@register_detector("motion", priority=50, supports=_supports_motion)
def _build_motion() -> MotionHighlightDetector:
    return MotionHighlightDetector()
