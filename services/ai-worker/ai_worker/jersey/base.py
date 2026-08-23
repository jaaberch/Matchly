"""Jersey number recognition.

The important design decision is *where the pixels come from*.

Detection and tracking run on the 640p proxy, because running them on 4K costs
roughly a hundred times as much and buys nothing for the density and motion
signals. But a player on a 640p wide shot is perhaps forty pixels tall, which
makes the number on their back about six pixels — unreadable by anything.

So jersey recognition is the one step that goes back to the master. It takes a
handful of moments per track, seeks the full-resolution recording at those
timestamps, and crops the player from *that*. The same player is then two hundred
pixels tall and the number is legible. A handful of seeks per track is cheap;
decoding the whole master would not be.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol, runtime_checkable

from ..detection import Box

#: Where the number sits on a shirt, as fractions of the player's box. Generous,
#: because the crop is fed to a reader that finds the digits within it.
REGION_TOP = 0.12
REGION_BOTTOM = 0.58
REGION_LEFT = 0.15
REGION_RIGHT = 0.85


@dataclasses.dataclass(frozen=True, slots=True)
class CropRequest:
    """One moment to look at, in master-video coordinates."""

    track_ref: str
    timestamp: float
    box: Box


def jersey_region(box: Box, *, scale: float = 1.0) -> Box:
    """The part of a player's box that holds the number.

    ``scale`` converts proxy coordinates to master coordinates: the boxes come
    from detection on the proxy, but the crop is taken from the master.
    """
    width, height = box.width, box.height
    return Box(
        x1=(box.x1 + width * REGION_LEFT) * scale,
        y1=(box.y1 + height * REGION_TOP) * scale,
        x2=(box.x1 + width * REGION_RIGHT) * scale,
        y2=(box.y1 + height * REGION_BOTTOM) * scale,
        confidence=box.confidence,
    )


@runtime_checkable
class JerseyRecognizer(Protocol):
    """Reads numbers from player crops.

    Implementations return one reading per crop they can make sense of, and
    simply omit the rest — a recognizer is never obliged to guess. The temporal
    vote decides what the omissions mean.
    """

    name: str

    def read(self, crops: list[LoadedCrop]) -> list[tuple[str, int, float]]:
        """``(track_ref, number, confidence)`` for each crop that read cleanly."""
        ...


@dataclasses.dataclass(slots=True)
class LoadedCrop:
    """A crop with its pixels attached, ready for a reader."""

    track_ref: str
    timestamp: float
    #: A numpy array, kept untyped here so this module imports without numpy.
    image: object
