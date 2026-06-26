"""dead-letter — list exhausted jobs and re-drive them (§5b)."""

from __future__ import annotations

from pathlib import Path

from trustrag.worker import DurableQueue, JobStatus, list_dead, redrive, redrive_all


def _queue(tmp_path: Path) -> DurableQueue:
    return DurableQueue(tmp_path / "manifest.db")


def test_list_dead_returns_only_dead_jobs(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("alive", "p", {})
    q.enqueue("gone", "p", {})
    q.mark_dead("gone", "p", stage="extract", reason="corrupt")
    dead = list_dead(q)
    assert [j.content_hash for j in dead] == ["gone"]
    assert dead[0].stage == "extract"
    assert dead[0].reason == "corrupt"


def test_redrive_moves_a_dead_job_back_to_queued(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {"k": "v"})
    q.mark_dead("h1", "p", stage="embed", reason="boom")
    job = redrive(q, "h1", "p")
    assert job.status is JobStatus.queued
    assert job.attempts == 0
    assert job.stage is None
    assert job.reason is None
    assert job.payload == {"k": "v"}  # payload preserved for the re-run


def test_redrive_all_revives_every_dead_job(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("d1", "p", {})
    q.enqueue("d2", "p", {})
    q.enqueue("ok", "p", {})
    q.mark_dead("d1", "p", stage="s", reason="r")
    q.mark_dead("d2", "p", stage="s", reason="r")
    revived = redrive_all(q)
    assert {j.content_hash for j in revived} == {"d1", "d2"}
    assert list_dead(q) == []
    assert len(q.list_by_status(JobStatus.queued)) == 3
