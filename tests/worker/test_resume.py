"""resume — re-enqueue every not-done job so a half-finished run continues (§5b)."""

from __future__ import annotations

from pathlib import Path

from citenexus.worker import DurableQueue, JobStatus, resume


def _queue(tmp_path: Path) -> DurableQueue:
    return DurableQueue(tmp_path / "manifest.db")


def test_resume_reenqueues_queued_running_failed_not_done(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("queued", "p", {})
    q.enqueue("running", "p", {})
    q.lease()  # leases "queued" first... order-independent: drive each explicitly below
    # Force a known mix of states:
    q.enqueue("failed", "p", {})
    q.enqueue("done", "p", {})
    q.mark_done("done", "p")
    q.mark_failed("failed", "p", stage="s", reason="r")
    # "running" → put it into running explicitly
    q.mark_running("running", "p")

    resumed = resume(q)
    resumed_hashes = {j.content_hash for j in resumed}
    assert "done" not in resumed_hashes
    assert {"queued", "running", "failed"} <= resumed_hashes
    # everything resumed is back to queued; done stays done
    for h in ("queued", "running", "failed"):
        assert q.get(h, "p").status is JobStatus.queued  # type: ignore[union-attr]
    assert q.get("done", "p").status is JobStatus.done  # type: ignore[union-attr]


def test_resume_leaves_done_untouched(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})
    q.mark_done("h1", "p")
    resumed = resume(q)
    assert resumed == []
    assert q.get("h1", "p").status is JobStatus.done  # type: ignore[union-attr]


def test_resume_excludes_dead_jobs(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})
    q.mark_dead("h1", "p", stage="s", reason="r")
    resumed = resume(q)
    assert resumed == []
    assert q.get("h1", "p").status is JobStatus.dead  # type: ignore[union-attr]


def test_resume_is_idempotent_for_done_hashes(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("done", "p", {})
    q.mark_done("done", "p")
    q.enqueue("pending", "p", {})
    resume(q)
    resume(q)  # twice — no duplication, done never revived
    assert q.get("done", "p").status is JobStatus.done  # type: ignore[union-attr]
    assert q.get("pending", "p").status is JobStatus.queued  # type: ignore[union-attr]
    assert len(q.list_by_status(JobStatus.queued)) == 1
