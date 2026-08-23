"""Jersey number recognition: crops, reading, and the temporal vote."""

from .base import CropRequest, JerseyRecognizer, LoadedCrop, jersey_region
from .recognizer import (
    EasyOcrJerseyRecognizer,
    NullJerseyRecognizer,
    build_recognizer,
    choose_moments,
    extract_crops,
)
from .voting import JerseyRead, JerseyVerdict, vote

__all__ = [
    "CropRequest",
    "EasyOcrJerseyRecognizer",
    "JerseyRead",
    "JerseyRecognizer",
    "JerseyVerdict",
    "LoadedCrop",
    "NullJerseyRecognizer",
    "build_recognizer",
    "choose_moments",
    "extract_crops",
    "jersey_region",
    "vote",
]
