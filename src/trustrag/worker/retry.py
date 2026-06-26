"""RetryPolicy — bounded attempts + a pure exponential-backoff function (spec §5b).

The slow path runs on a durable worker, so a transient failure (a flaky endpoint,
a throttled S3) must be retried a bounded number of times with growing gaps before
the job is dead-lettered. The backoff is computed as a *pure* function of the
attempt number so it is testable without ever sleeping: callers decide whether to
actually wait. The policy carries no state and is frozen.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RetryPolicy(BaseModel):
    """How many times to retry a transient failure, and how long to back off.

    ``max_attempts`` bounds the total number of executions (not just retries):
    after the ``max_attempts``-th failure the executor dead-letters the job.
    ``backoff_delay`` is exponential — ``base_delay * factor ** (attempt - 1)`` —
    optionally clamped to ``max_delay``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(gt=0)
    base_delay: float = Field(gt=0.0)
    factor: float = Field(default=2.0, gt=0.0)
    max_delay: float | None = Field(default=None, gt=0.0)

    def backoff_delay(self, attempt: int) -> float:
        """Delay (seconds) before ``attempt`` — pure, no sleeping, 1-indexed.

        ``attempt=1`` returns ``base_delay``; each further attempt multiplies by
        ``factor``; the result is capped at ``max_delay`` when one is set.
        """
        delay = self.base_delay * (self.factor ** (attempt - 1))
        if self.max_delay is not None:
            return min(delay, self.max_delay)
        return delay

    def should_retry(self, attempt: int) -> bool:
        """True iff another attempt is allowed after ``attempt`` (1-indexed)."""
        return attempt < self.max_attempts
