## Why

The slow path (full extraction + vision + embedding) and large backfills are too
expensive to run inline on the request path, and a process kill mid-backfill must
not lose or duplicate work. §5b calls for a durable background worker: a queue
that survives a crash, retries transient failures with backoff, dead-letters what
it can't complete, and resumes a half-finished run without reprocessing. The unit
of work is keyed by **content hash**, which is what makes every one of those
operations idempotent and therefore safe.

## What Changes

- Add a SQLite-backed **`DurableQueue`** (the `processing_manifest`): one row per
  `(partition, content_hash)` job, persisted via stdlib `sqlite3` so it survives a
  kill, with an in-memory/`tmp_path` mode for tests. Job status is a `StrEnum`:
  `queued, running, done, failed, dead`.
- Make enqueue **idempotent by content hash**: a hash already present in the
  partition (including an already-`done` one) is a no-op.
- Add a **`RetryPolicy`**: bounded `max_attempts` + a pure `backoff_delay(attempt)`
  that grows exponentially (optionally capped), computed without sleeping.
- Add a plugin-agnostic **`Executor`** that runs a job = a callable
  `(payload) -> result`: commit `done` on success, retry on a transient error,
  dead-letter on exhaustion or a permanent error — synchronous and deterministic.
- Add **dead-letter** helpers: list exhausted jobs (with failing stage + reason)
  and re-drive them back to `queued`; nothing is ever silently dropped.
- Add **resume**: re-enqueue every not-`done` job (queued/running/failed); because
  jobs are idempotent by hash, a half-finished run continues without duplication.

## Capabilities

### New Capabilities
- `worker-queue-resume`: a durable, content-hash-keyed background job queue with
  bounded exponential-backoff retries, a re-drivable dead-letter queue, and
  crash-safe resume — the off-request execution substrate for the slow path and
  large backfills (§5b).

### Modified Capabilities
<!-- none -->

## Impact

- New modules under `src/citenexus/worker/`: `queue.py`, `retry.py`, `executor.py`,
  `dlq.py`, `resume.py`, `__init__.py`. New tests under `tests/worker/`.
- Storage: a local SQLite file (the `processing_manifest`) via stdlib `sqlite3` —
  no new third-party dependency; hermetic in tests (tmp/in-memory only).
- Downstream: the L3 ingest pipeline and L2+ rebuild path enqueue content-hashed
  jobs here and consume the executor's terminal status; the partial-rebuild
  planner (`provenance-and-rebuild`) feeds the work that this worker drains.
