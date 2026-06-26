"""resume — re-enqueue every not-done job so a killed run continues (§5b).

After a crash the manifest can hold jobs stuck in ``running`` (interrupted
mid-flight), ``failed`` (awaiting a retry), or ``queued`` (never started).
Resuming re-enqueues exactly those — everything that is **not** ``done`` — back to
``queued``. ``done`` jobs are left alone (the work is finished) and ``dead`` jobs
are left for an explicit DLQ re-drive. Because jobs are idempotent by content
hash, re-enqueueing a half-finished job continues it without duplicating work.
"""

from __future__ import annotations

from trustrag.worker.queue import DurableQueue, Job, JobStatus

_RESUMABLE = (JobStatus.queued, JobStatus.running, JobStatus.failed)


def resume(queue: DurableQueue) -> list[Job]:
    """Re-enqueue all queued/running/failed jobs; return the re-enqueued jobs.

    ``done`` and ``dead`` jobs are untouched. Safe to call repeatedly.
    """
    resumed: list[Job] = []
    for status in _RESUMABLE:
        for job in queue.list_by_status(status):
            resumed.append(queue.requeue(job.content_hash, job.partition))
    return resumed
