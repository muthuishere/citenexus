## 1. Reproduce the leak (red)

- [x] 1.1 `tests/test_client_delete.py::test_revoke_removes_superseded_raw_blob`
      — ingest → re-ingest → `delete()` → assert the raw layer is empty. Scans
      storage rather than trusting the returned status, because the returned
      status was already `"deleted"`
- [x] 1.2 Multi-re-ingest variant: three versions, one revoke, no residue
- [x] 1.3 Shared-bucket safety case: a superseded checksum that is another
      document's CURRENT checksum must survive the revoke
- [x] 1.4 Ingest-side case: a re-ingest must leave only the current blob
- [x] 1.5 Confirm 1.1/1.2/1.4 fail and 1.3 passes before any fix (3 failed,
      9 passed)

## 2. Restore the severed reference

- [x] 2.1 Add `EtagManifest.superseded: dict[str, list[str]]`
- [x] 2.2 `record()` moves the previous checksum into the retired list, deduped
- [x] 2.3 `record()` removes the incoming checksum from the retired list — the
      A → B → A invariant (the current checksum is never retired)
- [x] 2.4 Add `superseded_of()` / `clear_superseded()`
- [x] 2.5 `forget()` (the revoke commit point) drops the retired history too
- [x] 2.6 Document on `owners_of` that retired references are NOT owners, and why
      that is the shared-bucket guard
- [x] 2.7 Unit tests: retirement, no-op re-record, A→B→A, retired-is-not-owner,
      forget, clear idempotence, JSON round-trip, and a pre-`superseded` manifest
      still loading

## 3. Sweep on revoke

- [x] 3.1 `client.delete` iterates `(current, *superseded_of(id))`
- [x] 3.2 Keep the `owners_of` guard per checksum — unchanged logic, wider input
- [x] 3.3 Green: 1.1 and 1.2 pass, 1.3 still passes

## 4. Reclaim on re-ingest

- [x] 4.1 `IngestPipeline._purge_superseded` — delete retired blobs, clear the
      list, save the manifest
- [x] 4.2 Call it AFTER the manifest commit point, never before (crash safety —
      see design.md)
- [x] 4.3 Green: 1.4 and 1.5 pass

## 5. ProcessingManifest

- [x] 5.1 Confirm nothing constructs, writes, or reads it (repo-wide grep: only
      its own definition, the package export, and two unit tests)
- [x] 5.2 Confirm `worker.queue.DurableQueue` already owns the same fact —
      SQLite table `processing_manifest`, `JobStatus` =
      queued/running/done/failed/dead
- [x] 5.3 Remove the model, its export from `citenexus.storage`, and its two
      tests; leave a note at the removal site naming the successor
- [x] 5.4 Amend the `document-revoke` requirement that promised slow-path state
      clearing, so the spec no longer asserts an unimplemented control
- [x] 5.5 Record the remaining narrower gap (revoke does not clear the durable
      queue row; the client holds no queue handle) as follow-up in design.md

## 6. Gates

- [x] 6.1 `uv run pytest -q` — 798 passed / 37 skipped (from 787/37: +13 new,
      −2 removed with `ProcessingManifest`)
- [x] 6.2 `uv run mypy src` — no issues in 136 source files
- [x] 6.3 `uv run ruff check` clean on every touched file
