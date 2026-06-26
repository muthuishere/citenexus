"""DurableQueue — a SQLite-backed, content-hash-keyed processing manifest (§5b).

The slow path and large backfills run on a durable worker, not inline, so the
queue of pending work must survive a kill. This is the ``processing_manifest``:
one row per ``(partition, content_hash)`` job in a local SQLite file (stdlib
``sqlite3``), committed on every transition so a crash loses nothing. Tests use
the default in-memory mode or a ``tmp_path`` file.

The content hash is the identity of a unit of work, so the queue is **idempotent
by hash**: enqueueing a hash that already exists in the partition is a no-op
(an already-``done`` hash is never re-queued). That is what makes retry and
resume safe — re-driving the same hash continues the same job without duplication.
"""

from __future__ import annotations

import json
import sqlite3
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class JobStatus(StrEnum):
    """Lifecycle of a unit of work in the processing manifest.

    ``queued`` → ``running`` → ``done`` on success; ``running`` → ``failed`` →
    (retry) ``running`` on a transient error; ``failed`` → ``dead`` once attempts
    are exhausted. ``done`` and ``dead`` are terminal (``dead`` is re-drivable).
    """

    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    dead = "dead"


class Job(BaseModel):
    """One row of the processing manifest — a content-hash-keyed unit of work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content_hash: str
    partition: str
    payload: dict[str, Any]
    status: JobStatus
    attempts: int = 0
    stage: str | None = None
    reason: str | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS processing_manifest (
    partition    TEXT    NOT NULL,
    content_hash TEXT    NOT NULL,
    payload      TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    stage        TEXT,
    reason       TEXT,
    PRIMARY KEY (partition, content_hash)
);
"""


class DurableQueue:
    """A durable, content-hash-keyed job queue backed by a SQLite file.

    Pass a filesystem path for durability across process restarts, or omit it
    for an in-memory queue (the default) in tests. The connection is held open
    for the queue's lifetime; call :meth:`close` to release it (or reopen the
    same path to recover persisted state).
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # -- writes ------------------------------------------------------------

    def enqueue(self, content_hash: str, partition: str, payload: dict[str, Any]) -> Job:
        """Insert a new ``queued`` job, or no-op if the hash already exists.

        Idempotent by ``(partition, content_hash)``: a hash already present in
        the partition — in any state, including ``done`` — is left untouched and
        its current row is returned.
        """
        self._conn.execute(
            "INSERT INTO processing_manifest "
            "(partition, content_hash, payload, status, attempts) "
            "VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT(partition, content_hash) DO NOTHING",
            (partition, content_hash, json.dumps(payload), JobStatus.queued.value),
        )
        self._conn.commit()
        job = self.get(content_hash, partition)
        assert job is not None  # just inserted or already present
        return job

    def lease(self) -> Job | None:
        """Claim the oldest ``queued`` job, mark it ``running``, and return it.

        Returns ``None`` when nothing is queued. Ordering is FIFO by insertion
        (SQLite rowid) so leasing is deterministic in tests.
        """
        row = self._conn.execute(
            "SELECT partition, content_hash FROM processing_manifest "
            "WHERE status = ? ORDER BY rowid LIMIT 1",
            (JobStatus.queued.value,),
        ).fetchone()
        if row is None:
            return None
        return self.mark_running(row["content_hash"], row["partition"])

    def mark_running(self, content_hash: str, partition: str) -> Job:
        """Transition a job to ``running``."""
        return self._set(content_hash, partition, status=JobStatus.running)

    def mark_done(self, content_hash: str, partition: str) -> Job:
        """Commit a job as ``done`` (terminal, idempotent), clearing failure info."""
        return self._set(
            content_hash, partition, status=JobStatus.done, stage=None, reason=None
        )

    def mark_failed(self, content_hash: str, partition: str, stage: str, reason: str) -> Job:
        """Record a transient failure: ``failed`` + 1 attempt + failing stage/reason."""
        return self._set(
            content_hash,
            partition,
            status=JobStatus.failed,
            stage=stage,
            reason=reason,
            bump_attempts=True,
        )

    def mark_dead(self, content_hash: str, partition: str, stage: str, reason: str) -> Job:
        """Dead-letter a job, recording the failing stage + reason (never dropped)."""
        return self._set(
            content_hash, partition, status=JobStatus.dead, stage=stage, reason=reason
        )

    def requeue(self, content_hash: str, partition: str) -> Job:
        """Reset a job to ``queued`` with attempts and failure info cleared.

        The primitive behind resume (§resume) and DLQ re-drive (§dlq): because
        jobs are idempotent by hash, requeueing continues the same work safely.
        """
        return self._set(
            content_hash,
            partition,
            status=JobStatus.queued,
            stage=None,
            reason=None,
            reset_attempts=True,
        )

    # -- reads -------------------------------------------------------------

    def get(self, content_hash: str, partition: str) -> Job | None:
        """Return the job for ``(partition, content_hash)``, or ``None``."""
        row = self._conn.execute(
            "SELECT * FROM processing_manifest WHERE partition = ? AND content_hash = ?",
            (partition, content_hash),
        ).fetchone()
        return None if row is None else _row_to_job(row)

    def list_by_status(self, status: JobStatus) -> list[Job]:
        """All jobs in ``status``, FIFO by insertion."""
        rows = self._conn.execute(
            "SELECT * FROM processing_manifest WHERE status = ? ORDER BY rowid",
            (status.value,),
        ).fetchall()
        return [_row_to_job(row) for row in rows]

    # -- internals ---------------------------------------------------------

    def _set(
        self,
        content_hash: str,
        partition: str,
        *,
        status: JobStatus,
        stage: str | None = None,
        reason: str | None = None,
        bump_attempts: bool = False,
        reset_attempts: bool = False,
    ) -> Job:
        attempts_sql = "attempts"
        if bump_attempts:
            attempts_sql = "attempts + 1"
        elif reset_attempts:
            attempts_sql = "0"
        cursor = self._conn.execute(
            "UPDATE processing_manifest SET status = ?, stage = ?, reason = ?, "
            f"attempts = {attempts_sql} WHERE partition = ? AND content_hash = ?",
            (status.value, stage, reason, partition, content_hash),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"no job for partition={partition!r} content_hash={content_hash!r}")
        self._conn.commit()
        job = self.get(content_hash, partition)
        assert job is not None  # row was just updated
        return job


def _row_to_job(row: sqlite3.Row) -> Job:
    payload: dict[str, Any] = json.loads(row["payload"])
    return Job(
        content_hash=row["content_hash"],
        partition=row["partition"],
        payload=payload,
        status=JobStatus(row["status"]),
        attempts=row["attempts"],
        stage=row["stage"],
        reason=row["reason"],
    )
