## Context

Raw blobs are content-addressed: `raw/<P>/<sha256>` (`ingest/pipeline.py:169`).
The *only* index from a document to its bytes is the etag manifest, and that
index is single-valued. Overwriting it is therefore not just forgetting a version
— it is severing the last reference to a live object. The bytes stay; the name
does not.

Everything else about revoke is already correct: the removal order is resumable,
the etag entry is the commit point, and the reference guard (`owners_of`)
correctly preserves blobs shared by identical bytes. The defect is entirely one
of *reachability*, so the fix must restore a reference, not change the deletion
logic.

Constraints: shared buckets are the normal deployment (ADR-0008 exists because
of them), so nothing may be deleted that cannot be proven to belong to the
document being revoked. The manifest is a single JSON object read and written
whole, so any new state must stay O(documents).

## Goals / Non-Goals

**Goals:**

- A revoke removes every raw blob the document ever wrote.
- Never delete bytes another document still relies on, on a shared bucket, under
  any interleaving.
- Close the leak at the source too: a re-ingest should not accumulate dead copies
  of superseded document text.
- Survive a crash at any point without losing the reference again.

**Non-Goals:**

- Reclaiming blobs stranded *before* this change. Their checksums are gone from
  the manifest; only an unguided byte-level sweep could find them.
- Byte-level orphans generally (crashed ingests leave `raw/` and `knowledge/`
  artifacts with no manifest entry). That is ADR-0008 territory and explicitly
  outside a document-keyed view.
- Versioning or retention. `superseded` is a deletion ledger, not history: the
  bytes are gone as soon as they can be, and the list is cleared with them.

## Decisions

### The manifest remembers retired checksums; it does not sweep

Two mechanisms could find the stranded blob.

- **A prefix sweep** — list `raw/<P>/` and delete blobs no manifest entry
  references. Rejected, and not marginally. It is unsafe by construction on the
  exact deployment this library targets: a shared bucket may hold blobs written
  by another partition, another tenant, another tool, or an in-flight ingest that
  has not reached its commit point yet. "Unreferenced by *my* manifest" does not
  imply "mine to delete", and a sweep cannot tell the difference. It also inverts
  the cost model (an O(objects) LIST on every revoke, paginated on S3, for a
  question that should be O(1)), and it would race any concurrent ingest between
  `put_bytes` and `save_manifest`. A sweep is a garbage collector, and this
  library has no ownership metadata that would make one sound.

- **The manifest tracking prior checksums** — chosen. It restores exactly the
  reference that was severed, at the point it was severed, and it keeps the
  existing proof obligation intact: we delete a blob because *this document*
  recorded writing it and no other document currently claims it. Nothing is ever
  deleted on the basis of absence-of-evidence. Cost is one list of hex strings
  per re-ingested document, in a file already read and written on every ingest.

The guard stays `owners_of(checksum, excluding=document_id)`, which considers
only **current** references. Retired references deliberately do not keep a blob
alive: those bytes are dead for their document too. So the survival rule is
"some document currently points here", which is precisely the property that
makes deletion safe.

### Reclaim at re-ingest, after the commit point

`_purge_superseded` runs *after* `save_manifest` records the retirement, not
before. That ordering is the crash-safety argument:

- Die before the manifest write → nothing was retired; the old checksum is still
  current and still reachable.
- Die after the manifest write, before the purge → the retired checksum is
  durably recorded, so the next ingest reclaims it and a revoke would have found
  it anyway.
- Die mid-purge → the same, minus whatever was already deleted; `delete_prefix`
  on an absent key is a no-op, so re-running is idempotent.

At no point does a window exist where a blob is both undeleted and unnameable —
which is the entire defect being fixed. The cost is a second manifest write, paid
only on a genuine re-ingest.

Doing it at ingest rather than deferring everything to revoke matters for the
same reason the bug matters: a superseded version of a document is full source
text, and keeping unreachable copies of it around indefinitely is the condition
right-to-erasure exists to prevent.

### `record()` keeps the current checksum out of the retired list

A document can return to a previous version (A → B → A). If `superseded` still
listed A while `etags` pointed at A, the next purge would delete the live blob.
`record()` therefore removes the incoming checksum from the retired list as part
of recording it, making "the current checksum is never retired" an invariant of
the model rather than a caller obligation.

### `ProcessingManifest` is removed, not wired

`ProcessingManifest.clear_status` documents itself as "called on a revoke", and
nothing in the repo ever constructs, writes, or reads the model. The living
`document-revoke` spec carries the matching promise ("clear the checksum's
slow-path queue/processing state"), so the spec has been ahead of the code here
since the capability shipped.

It was not wired, because the capability already exists elsewhere:
`worker.queue.DurableQueue` persists `(partition, content_hash) → status` in
SQLite, in a table named `processing_manifest`, with a `JobStatus` enum of
exactly `queued/running/done/failed/dead`. Wiring the JSON model would create a
second status store for one fact; whichever one a future revoke cleared would
become the truth and the other would rot silently. One store, or none.

**This leaves a real, narrower gap, stated rather than hidden:** revoke still
does not clear the *durable queue* row for a purged checksum. It cannot today —
`CiteNexus` holds no queue handle (the queue is constructed inside
`IngestPipeline`), so closing it means plumbing the queue to the client, which is
a wider change than a leak fix should carry. Tracked as follow-up; the
`document-revoke` requirement is amended here to describe what the code actually
guarantees, so the spec stops asserting an unimplemented control.

## Risks / Trade-offs

- **The retired list grows on repeated re-ingest.** Bounded in practice: it is
  cleared at the end of every successful ingest, so it only accumulates across
  crashed purges. Worst case it is a list of 64-char strings per document in a
  JSON file that is already read whole.
- **Pre-existing stranded blobs remain.** Unrecoverable from the manifest by
  construction. Deployments that have re-ingested before this change need an
  out-of-band audit; this is exactly the byte-level scope ADR-0008 says its
  document-keyed report does not cover.
- **`delete_prefix` is not the same operation on both backends.** On local FS it
  unlinks one file; on S3 it deletes every key with that prefix. A checksum is a
  full sha256 hex string, so prefix collision is not realistic — but this is
  pre-existing behavior that the sweep now exercises more often, and it is why a
  *directory-level* sweep was rejected above.

## Open Questions

- Should revoke clear the durable-queue row (and thus take a queue handle)? The
  follow-up above. It is a leak of slow-path *status*, not of document content,
  so it is lower severity than what this change fixes.
