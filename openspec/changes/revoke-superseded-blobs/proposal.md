## Why

`delete()` reports `status="deleted"` while leaving the revoked document's
earlier full text in object storage.

The etag manifest is a single-valued `document_id → checksum` map
(`storage/manifest.py:31`). A re-ingest overwrites it (`ingest/pipeline.py:169`)
without deleting the blob the old checksum named, and `client.delete` deletes
only the checksum it currently finds recorded (`client.py:513,536`). So the
previous blob becomes unreferenced *and* unreachable: nothing in the system can
name those bytes again, including the revoke that is supposed to remove them.

Measured in `spikes/adr-0008-reconcile/` against real storage: ingest `victim` →
re-ingest `victim` with new bytes → `delete("victim")` returns
`status="deleted"`, and `raw/workspace=spike/3c58d7e6…` — the full text of the
revoked document's first version — is still there. Every other layer (vector
rows, BM25, structure index, wiki, graph, etag manifest) came back clean, which
is what makes this dangerous: the revoke looks complete from every observable
surface except the bucket itself.

For a library whose stated capability is "retract a document from every layer",
in the deployments that capability exists for (right-to-erasure, privileged-
document clawback), this is a correctness gap in a feature that reports success.

It is also a **blocking precondition for ADR-0008**. Reconciliation's remediation
step removes orphans through this same `delete.py` path, so
reconcile → remediate → reconcile would certify a bucket clean while revoked
bytes remained — an actively false assurance, which is worse than no report.

## What Changes

- `EtagManifest` gains `superseded: dict[str, list[str]]` — the checksums a
  document has retired. `record()` moves the previous checksum there instead of
  dropping it, so retired bytes stay *nameable* and therefore revocable.
- `delete()` sweeps every checksum the document ever owned — current plus
  retired — instead of only the current one. Each deletion keeps the existing
  reference guard: a blob is removed only when no OTHER document *currently*
  owns that checksum.
- A re-ingest reclaims its own superseded blob immediately, after the manifest
  commit point, so the leak is closed at the source and not only at revoke time.
  If the process dies mid-purge the retired entry is already durable, so the next
  ingest — or the revoke — finishes the job.
- `forget()` (the revoke commit point) drops the retired history with the entry.
- **Removed:** the dead `ProcessingManifest` model. It was never constructed or
  written by anything, and its documented job — `content_hash` → queued/running/
  done/failed/dead — is already done by `worker.queue.DurableQueue`, whose SQLite
  table is literally named `processing_manifest` and whose `JobStatus` enum is
  exactly that status set.

**Not fixed here:** blobs already stranded by re-ingests that happened before
this change. Their checksums were overwritten and are unrecoverable from the
manifest by construction; only a byte-level sweep could find them, and that is
out of scope (see `design.md`).

## Capabilities

### Modified Capabilities
- `document-revoke`: revoke removes every raw blob the document ever wrote, not
  only its current one; the reference guard is unchanged and still shared-bucket
  safe.
- `ingest-pipeline`: a re-ingest records and then reclaims the checksum it
  retires.

## Impact

- **Code:** `python/src/citenexus/storage/manifest.py` (new `superseded` field +
  `superseded_of` / `clear_superseded`, `record`/`forget` updated,
  `ProcessingManifest` removed), `python/src/citenexus/ingest/pipeline.py`
  (`_purge_superseded`), `python/src/citenexus/client.py` (`delete` sweeps the
  retired set).
- **Data:** the etag manifest JSON gains an optional `superseded` key. Manifests
  written before this change load unchanged (the field defaults to empty), and no
  port reads this file — `EtagManifest` has no Go/JS/Rust counterpart.
- **API:** `citenexus.storage.ProcessingManifest` is removed from the package
  exports. Nothing constructed it, so no behavior changes.
- **Tests:** 5 new `tests/test_client_delete.py` cases (leak reproduction,
  multi-re-ingest, shared-owner survival, ingest-side reclaim), 8 new
  `tests/storage/test_manifest.py` cases; 2 `ProcessingManifest` tests removed
  with the model.
- **Ports:** none. Go / JS / Rust do not implement the etag manifest or revoke.
- **Not touched:** `answer/`, retrieval, conformance vectors.
