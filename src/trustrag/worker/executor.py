"""Executor — drive one job through the retry policy to a terminal status (§5b).

A plugin-agnostic executor: a job is just a callable ``(payload) -> result``. The
executor leases the job, runs the callable, and applies the policy — commit
``done`` on success, retry on a :class:`TransientError`, and dead-letter once the
bounded attempts are exhausted. A non-transient (permanent) error is dead-lettered
immediately, never retried. It is synchronous and deterministic — no threads and
no real sleeping — so the whole retry/dead-letter path is provable offline. Because
the queue is idempotent by hash, re-running a ``done`` job is a no-op.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trustrag.worker.queue import DurableQueue, Job, JobStatus
from trustrag.worker.retry import RetryPolicy

JobRunner = Callable[[dict[str, Any]], Any]


class TransientError(Exception):
    """A retryable failure: the executor retries it until attempts are exhausted.

    Carries the ``stage`` at which work failed so the dead-letter record names
    where it broke. Any other exception type is treated as permanent.
    """

    def __init__(self, reason: str, *, stage: str) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason


class Executor:
    """Runs jobs through a :class:`RetryPolicy` to a terminal status."""

    def __init__(self, queue: DurableQueue, policy: RetryPolicy) -> None:
        self._queue = queue
        self._policy = policy

    def run(self, content_hash: str, partition: str, runner: JobRunner) -> Job:
        """Execute one job to a terminal (``done`` or ``dead``) status.

        Idempotent: an already-``done`` job is returned untouched without invoking
        ``runner``. On a transient error the job is marked ``failed`` and retried
        up to ``max_attempts``; the policy's ``backoff_delay`` is the gap a real
        worker would wait (computed, not slept). On exhaustion or a permanent
        error the job is dead-lettered with the failing stage and reason.
        """
        job = self._queue.get(content_hash, partition)
        if job is None:
            raise KeyError(f"no job for partition={partition!r} content_hash={content_hash!r}")
        if job.status in (JobStatus.done, JobStatus.dead):
            return job

        attempt = 0
        while True:
            attempt += 1
            self._queue.mark_running(content_hash, partition)
            try:
                runner(job.payload)
            except TransientError as exc:
                if self._policy.should_retry(attempt):
                    self._queue.mark_failed(content_hash, partition, exc.stage, exc.reason)
                    # A real worker would wait this long before the next attempt:
                    _ = self._policy.backoff_delay(attempt + 1)
                    continue
                return self._queue.mark_dead(content_hash, partition, exc.stage, exc.reason)
            except Exception as exc:  # permanent failure — do not retry
                return self._queue.mark_dead(content_hash, partition, "execute", str(exc))
            else:
                return self._queue.mark_done(content_hash, partition)
