"""Shared building blocks used by the API and the background workers.

Everything in this package must be importable without side effects: no database
connections, no network calls, no Celery workers started at import time.
"""

__version__ = "0.1.0"
