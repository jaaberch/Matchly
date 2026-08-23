"""The pipeline step contract.

A step is a plain function that takes a :class:`StepContext` and returns a JSON
result. It knows nothing about Celery, retries or job rows — the runner owns all
of that — so steps stay easy to test and easy to replace.

Registration happens by import: whichever worker process imports a step module
can execute that step. That is what lets the CV steps move to a GPU node later
without any change to the orchestration.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from ..config import Settings
from ..domain import JobStep, Match, ProcessingJob, Video
from ..storage import ObjectStorage


class StepError(RuntimeError):
    """A step failed in a way worth recording. Message goes to ``last_error``."""


class StepSkipped(Exception):  # noqa: N818 - control flow, not an error
    """Raised by a step that has nothing to do. Recorded as SKIPPED, not FAILED."""


@dataclasses.dataclass(slots=True)
class StepContext:
    session: Any
    video: Video
    match: Match
    job: ProcessingJob
    storage: ObjectStorage
    settings: Settings
    #: Scratch directory for this pipeline run; cleaned up by the runner.
    workdir: Any
    force: bool = False

    @property
    def originals_bucket(self) -> str:
        return self.settings.storage_bucket_originals

    @property
    def derived_bucket(self) -> str:
        return self.settings.storage_bucket_derived


StepFn = Callable[[StepContext], dict[str, Any]]

_REGISTRY: dict[JobStep, StepFn] = {}


def register_step(step: JobStep) -> Callable[[StepFn], StepFn]:
    def decorator(function: StepFn) -> StepFn:
        _REGISTRY[step] = function
        return function

    return decorator


def get_step(step: JobStep) -> StepFn | None:
    return _REGISTRY.get(step)


def registered_steps() -> frozenset[JobStep]:
    return frozenset(_REGISTRY)


def clear_registry() -> None:
    """Test helper."""
    _REGISTRY.clear()
