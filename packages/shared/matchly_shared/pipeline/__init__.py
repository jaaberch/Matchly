"""Video processing pipeline: the step contract and the job runner.

Step *implementations* live in the worker services; this package owns the
contract and the state machine, so the API can read job state without importing
ffmpeg or any CV dependency.
"""

from .fingerprint import fingerprint
from .registry import (
    StepContext,
    StepError,
    StepFn,
    StepSkipped,
    clear_registry,
    get_step,
    register_step,
    registered_steps,
)
from .runner import (
    STUCK_JOB_TIMEOUT,
    PipelineResult,
    get_or_create_job,
    reap_stuck_jobs,
    run_pipeline,
)

__all__ = [
    "STUCK_JOB_TIMEOUT",
    "PipelineResult",
    "StepContext",
    "StepError",
    "StepFn",
    "StepSkipped",
    "clear_registry",
    "fingerprint",
    "get_or_create_job",
    "get_step",
    "reap_stuck_jobs",
    "register_step",
    "registered_steps",
    "run_pipeline",
]
