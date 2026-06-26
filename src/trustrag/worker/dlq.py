"""Dead-letter queue — list exhausted jobs and re-drive them (§5b).

A job whose retries are exhausted is moved to ``dead`` with the failing stage and
reason recorded — never silently dropped. The dead-letter view lets an operator
inspect those failures and, once the underlying cause is fixed, re-drive them:
re-driving resets a dead job to ``queued`` (attempts and failure info cleared) so
the executor can run it again. Idempotency by content hash keeps the re-run safe.
"""

from __future__ import annotations

from trustrag.worker.queue import DurableQueue, Job, JobStatus


def list_dead(queue: DurableQueue) -> list[Job]:
    """All dead-lettered jobs, with their failing stage + reason."""
    return queue.list_by_status(JobStatus.dead)


def redrive(queue: DurableQueue, content_hash: str, partition: str) -> Job:
    """Re-drive one dead job back to ``queued`` (attempts + failure info cleared)."""
    return queue.requeue(content_hash, partition)


def redrive_all(queue: DurableQueue) -> list[Job]:
    """Re-drive every dead-lettered job; return the re-driven jobs."""
    return [redrive(queue, job.content_hash, job.partition) for job in list_dead(queue)]
