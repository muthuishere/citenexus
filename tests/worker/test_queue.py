"""DurableQueue — SQLite-backed, content-hash keyed, idempotent (spec §5b)."""

from __future__ import annotations

from pathlib import Path

from trustrag.worker import DurableQueue, JobStatus


def _queue(tmp_path: Path) -> DurableQueue:
    return DurableQueue(tmp_path / "manifest.db")


def test_enqueue_then_lease_round_trips(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "org/acme", {"uri": "s3://b/doc1"})
    leased = q.lease()
    assert leased is not None
    assert leased.content_hash == "h1"
    assert leased.partition == "org/acme"
    assert leased.payload == {"uri": "s3://b/doc1"}
    assert leased.status is JobStatus.running


def test_lease_returns_none_when_empty(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    assert q.lease() is None


def test_lease_is_fifo_by_insertion(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})
    q.enqueue("h2", "p", {})
    first = q.lease()
    second = q.lease()
    assert first is not None and second is not None
    assert (first.content_hash, second.content_hash) == ("h1", "h2")


def test_enqueue_is_idempotent_by_hash(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {"v": 1})
    q.enqueue("h1", "p", {"v": 2})  # same hash+partition → no-op, original wins
    job = q.get("h1", "p")
    assert job is not None
    assert job.payload == {"v": 1}
    assert len(q.list_by_status(JobStatus.queued)) == 1


def test_re_enqueue_of_done_hash_is_a_no_op(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})
    q.mark_done("h1", "p")
    q.enqueue("h1", "p", {})  # already done → stays done, not re-queued
    job = q.get("h1", "p")
    assert job is not None
    assert job.status is JobStatus.done
    assert q.list_by_status(JobStatus.queued) == []


def test_same_hash_different_partition_are_distinct(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p1", {})
    q.enqueue("h1", "p2", {})
    assert len(q.list_by_status(JobStatus.queued)) == 2


def test_status_transitions_queued_running_done(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})
    assert q.get("h1", "p").status is JobStatus.queued  # type: ignore[union-attr]
    q.lease()
    assert q.get("h1", "p").status is JobStatus.running  # type: ignore[union-attr]
    q.mark_done("h1", "p")
    assert q.get("h1", "p").status is JobStatus.done  # type: ignore[union-attr]


def test_mark_failed_records_stage_and_reason_and_counts_attempts(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})
    q.lease()
    job = q.mark_failed("h1", "p", stage="embed", reason="boom")
    assert job.status is JobStatus.failed
    assert job.stage == "embed"
    assert job.reason == "boom"
    assert job.attempts == 1


def test_mark_dead_records_failing_stage_and_reason(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})
    job = q.mark_dead("h1", "p", stage="extract", reason="corrupt")
    assert job.status is JobStatus.dead
    assert job.stage == "extract"
    assert job.reason == "corrupt"


def test_state_survives_reopening_the_file(tmp_path: Path) -> None:
    db = tmp_path / "manifest.db"
    q1 = DurableQueue(db)
    q1.enqueue("h1", "p", {"k": "v"})
    q1.mark_done("h1", "p")
    q1.close()
    q2 = DurableQueue(db)
    job = q2.get("h1", "p")
    assert job is not None
    assert job.status is JobStatus.done
    assert job.payload == {"k": "v"}
