"""Durable worker — queue, retry/backoff, dead-letter, resume, executor (§5b).

The slow path and large backfills run here, off the request path. A SQLite-backed
:class:`DurableQueue` (the ``processing_manifest``) holds content-hash-keyed jobs
that survive a kill; :class:`RetryPolicy` bounds retries with pure exponential
backoff; :class:`Executor` drives a job to a terminal status; :func:`resume`
re-enqueues a half-finished run; and the dead-letter helpers list and re-drive
exhausted jobs. Everything is idempotent by content hash, so retry and resume
never duplicate work.
"""

from trustrag.worker.dlq import list_dead, redrive, redrive_all
from trustrag.worker.executor import Executor, JobRunner, TransientError
from trustrag.worker.queue import DurableQueue, Job, JobStatus
from trustrag.worker.resume import resume
from trustrag.worker.retry import RetryPolicy

__all__ = [
    "DurableQueue",
    "Executor",
    "Job",
    "JobRunner",
    "JobStatus",
    "RetryPolicy",
    "TransientError",
    "list_dead",
    "redrive",
    "redrive_all",
    "resume",
]
