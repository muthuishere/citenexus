## ADDED Requirements

### Requirement: Durable content-hash-keyed queue

The worker SHALL provide a durable job queue (the `processing_manifest`) keyed by
`(partition, content_hash)`, backed by a local SQLite file via the standard-library
`sqlite3` module so that enqueued work survives a process kill. Each job SHALL carry
a status drawn from the enumeration `queued`, `running`, `done`, `failed`, `dead`,
plus its attempt count and, when failed or dead, the failing stage and reason. The
queue SHALL offer an in-memory or temporary-file mode for tests.

#### Scenario: Enqueue then lease

- **WHEN** a job is enqueued for a content hash and then leased
- **THEN** the leased job exposes that content hash, its partition, and its payload,
  and its status is `running`

#### Scenario: State survives reopening the file

- **WHEN** a job is marked `done`, the queue is closed, and the same SQLite file is
  reopened as a new queue
- **THEN** the job is still present with status `done` and its original payload

### Requirement: Enqueue is idempotent by content hash

Enqueueing a content hash that already exists in the partition SHALL be a no-op: the
existing row is left unchanged and no duplicate job is created. In particular,
enqueueing a hash that is already `done` SHALL NOT return it to the `queued` state.

#### Scenario: Re-enqueue of a done hash is a no-op

- **WHEN** a content hash is enqueued, marked `done`, and then enqueued again
- **THEN** the job remains `done` and no queued job exists for that hash

#### Scenario: Same hash in a different partition is distinct

- **WHEN** the same content hash is enqueued under two different partitions
- **THEN** two separate queued jobs exist, one per partition

### Requirement: Bounded retries with pure exponential backoff

The worker SHALL provide a retry policy with a bounded maximum number of attempts
and a backoff-delay function that grows exponentially with the attempt number
(optionally capped at a maximum). The backoff delay SHALL be computed as a pure
function — no sleeping and no side effects — so it is testable in isolation.

#### Scenario: Backoff grows exponentially

- **WHEN** `backoff_delay` is evaluated for attempts 1, 2, 3, 4 with base delay 1.0
  and factor 2.0
- **THEN** it returns 1.0, 2.0, 4.0, 8.0 respectively, and repeated evaluation of the
  same attempt returns the same value

#### Scenario: Attempts are bounded

- **WHEN** the policy has `max_attempts` of 3
- **THEN** another attempt is allowed after attempts 1 and 2 but not after attempt 3

### Requirement: Executor drives a job to a terminal status

The worker SHALL provide a plugin-agnostic executor that runs a job as a callable
`(payload) -> result` under the retry policy. On success it SHALL commit the job as
`done`; on a transient error it SHALL mark the job `failed` and retry up to the
bounded attempt limit; and on exhaustion it SHALL dead-letter the job. The executor
SHALL be synchronous and deterministic, requiring no real threads or sleeping. An
already-`done` job SHALL NOT be re-executed (idempotent re-run).

#### Scenario: Fails twice then succeeds ends done

- **WHEN** a job raises a transient error on its first two attempts and then succeeds,
  under a policy of 3 attempts
- **THEN** the runner is invoked three times and the job ends `done`

#### Scenario: Re-running a done job is a no-op

- **WHEN** a job that is already `done` is run again
- **THEN** the runner is not invoked and the job stays `done`

### Requirement: Dead-letter exhausted jobs with stage and reason

When a job's attempts are exhausted the worker SHALL move it to `dead`, recording the
failing stage and reason; a dead-lettered job SHALL never be silently dropped. The
worker SHALL list dead jobs and SHALL re-drive a dead job back to `queued` with its
attempt count and failure information cleared, so it can be run again.

#### Scenario: A job that always fails ends dead with stage and reason

- **WHEN** a job raises a transient error on every attempt under a policy of 3 attempts
- **THEN** the job ends `dead` and records the failing stage and reason

#### Scenario: Re-drive returns a dead job to queued

- **WHEN** a dead job is re-driven
- **THEN** its status becomes `queued`, its attempt count is 0, its failing stage and
  reason are cleared, and its payload is preserved

### Requirement: Resume re-enqueues every not-done job

The worker SHALL provide a resume operation that re-enqueues every job that is not
`done` — that is, jobs in `queued`, `running`, or `failed` — back to `queued`, while
leaving `done` jobs untouched. Because jobs are idempotent by content hash, resuming a
half-finished run SHALL continue it without duplicating work.

#### Scenario: Resume re-enqueues queued, running and failed but not done

- **WHEN** the manifest holds jobs in `queued`, `running`, `failed`, and `done`, and
  resume is invoked
- **THEN** the queued, running, and failed jobs are returned to `queued` and the `done`
  job remains `done`

#### Scenario: Resume is idempotent for done hashes

- **WHEN** resume is invoked twice over a manifest containing a `done` job and a pending
  job
- **THEN** the `done` job is never revived and exactly one queued job exists for the
  pending hash
