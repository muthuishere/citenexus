"""Executor — drive a job through the retry policy to a terminal status (§5b)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from citenexus.worker import (
    DurableQueue,
    Executor,
    JobStatus,
    RetryPolicy,
    TransientError,
)


def _queue(tmp_path: Path) -> DurableQueue:
    return DurableQueue(tmp_path / "manifest.db")


def test_job_succeeds_first_try_commits_done(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {"n": 1})
    seen: list[dict[str, Any]] = []

    def run(payload: dict[str, Any]) -> str:
        seen.append(payload)
        return "ok"

    executor = Executor(q, RetryPolicy(max_attempts=3, base_delay=1.0))
    job = executor.run("h1", "p", run)
    assert job.status is JobStatus.done
    assert seen == [{"n": 1}]


def test_job_that_fails_twice_then_succeeds_ends_done(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})
    calls = {"n": 0}

    def run(_: dict[str, Any]) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("flaky", stage="embed")
        return "ok"

    executor = Executor(q, RetryPolicy(max_attempts=3, base_delay=1.0))
    job = executor.run("h1", "p", run)
    assert calls["n"] == 3
    assert job.status is JobStatus.done


def test_job_that_always_fails_ends_dead_with_stage_and_reason(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})

    def run(_: dict[str, Any]) -> str:
        raise TransientError("still broken", stage="vision")

    executor = Executor(q, RetryPolicy(max_attempts=3, base_delay=1.0))
    job = executor.run("h1", "p", run)
    assert job.status is JobStatus.dead
    assert job.stage == "vision"
    assert job.reason == "still broken"


def test_executor_attempts_exactly_max_attempts_times(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})
    calls = {"n": 0}

    def run(_: dict[str, Any]) -> str:
        calls["n"] += 1
        raise TransientError("nope", stage="x")

    Executor(q, RetryPolicy(max_attempts=4, base_delay=1.0)).run("h1", "p", run)
    assert calls["n"] == 4


def test_running_an_already_done_job_is_a_no_op(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})
    q.mark_done("h1", "p")
    calls = {"n": 0}

    def run(_: dict[str, Any]) -> str:
        calls["n"] += 1
        return "ok"

    job = Executor(q, RetryPolicy(max_attempts=3, base_delay=1.0)).run("h1", "p", run)
    assert job.status is JobStatus.done
    assert calls["n"] == 0  # idempotent: not re-executed


def test_idempotent_rerun_produces_same_terminal_status(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})

    def run(_: dict[str, Any]) -> str:
        return "ok"

    executor = Executor(q, RetryPolicy(max_attempts=3, base_delay=1.0))
    first = executor.run("h1", "p", run)
    second = executor.run("h1", "p", run)
    assert first.status is second.status is JobStatus.done


def test_non_transient_error_goes_straight_to_dead(tmp_path: Path) -> None:
    q = _queue(tmp_path)
    q.enqueue("h1", "p", {})
    calls = {"n": 0}

    def run(_: dict[str, Any]) -> str:
        calls["n"] += 1
        raise ValueError("permanent")

    job = Executor(q, RetryPolicy(max_attempts=3, base_delay=1.0)).run("h1", "p", run)
    assert job.status is JobStatus.dead
    assert job.reason == "permanent"
    assert calls["n"] == 1  # permanent failures are not retried
