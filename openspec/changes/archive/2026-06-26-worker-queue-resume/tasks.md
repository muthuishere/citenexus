## 1. Tests first (red)

- [x] 1.1 `tests/worker/test_queue.py`: enqueue→lease round-trips; lease is FIFO and
      returns `None` when empty; enqueue is idempotent by hash; re-enqueue of a
      `done` hash is a no-op; same hash in different partitions is distinct; status
      transitions queued→running→done; `mark_failed` records stage/reason + attempts;
      `mark_dead` records stage/reason; state survives reopening the SQLite file.
- [x] 1.2 `tests/worker/test_retry.py`: `backoff_delay` grows exponentially and is
      capped by `max_delay`; it is pure; `should_retry` respects bounded attempts;
      the policy is frozen.
- [x] 1.3 `tests/worker/test_executor.py`: success commits `done`; fails-twice-then-
      succeeds ends `done`; always-fails ends `dead` with stage+reason; runs exactly
      `max_attempts` times; an already-`done` job is not re-executed; idempotent
      re-run yields the same terminal status; a non-transient error goes straight to
      `dead` without retry.
- [x] 1.4 `tests/worker/test_resume.py`: resume re-enqueues queued/running/failed but
      not done; leaves done untouched; excludes dead; is idempotent for done hashes.
- [x] 1.5 `tests/worker/test_dlq.py`: `list_dead` returns only dead jobs with
      stage/reason; `redrive` returns a dead job to `queued` with attempts/failure
      cleared and payload preserved; `redrive_all` revives every dead job.

## 2. Implement (green)

- [x] 2.1 `src/trustrag/worker/queue.py`: `JobStatus` `StrEnum`; frozen `Job` model;
      SQLite-backed `DurableQueue` (`processing_manifest`) with idempotent `enqueue`,
      `lease`, `mark_running/done/failed/dead`, `requeue`, `get`, `list_by_status`,
      `close`; default in-memory mode + file path for durability.
- [x] 2.2 `src/trustrag/worker/retry.py`: frozen `RetryPolicy` with `max_attempts`,
      pure `backoff_delay(attempt)`, and `should_retry(attempt)`.
- [x] 2.3 `src/trustrag/worker/executor.py`: `TransientError` (carries stage);
      `Executor.run` driving success→done / transient→retry / exhaustion-or-permanent
      →dead; idempotent on an already-`done` job; synchronous + deterministic.
- [x] 2.4 `src/trustrag/worker/dlq.py`: `list_dead`, `redrive`, `redrive_all`.
- [x] 2.5 `src/trustrag/worker/resume.py`: `resume` re-enqueues every not-`done` job.
- [x] 2.6 `src/trustrag/worker/__init__.py`: export the public surface.

## 3. Verify

- [x] 3.1 `uv run pytest tests/worker -q` passes.
- [x] 3.2 `uv run ruff check src/trustrag/worker tests/worker` clean.
- [x] 3.3 `uv run mypy src/trustrag/worker tests/worker` clean (strict).
- [x] 3.4 `npx -y @fission-ai/openspec@latest validate worker-queue-resume` passes.
