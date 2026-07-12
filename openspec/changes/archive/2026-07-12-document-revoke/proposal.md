## Why

Ingest is one-way today: there is no way to remove a document once it is in. The
only removal anywhere is dropping the whole leaf table — never one document. Real
products need surgical removal: a source is **corrected or retracted**, a document
is **re-scoped or expired**, or a data subject exercises a **right-to-be-forgotten /
GDPR erasure**. For an evidence-first library used in legal, medical, and
compliance settings, "I can't un-cite a retracted source" is a blocker — a
deleted document must stop being retrievable and stop being citable, or the
cite-or-abstain guarantee is only half true. Delete must be **first-class**,
**surgical** (one document), **idempotent**, and honest about what it removes.

## What Changes

- Add **`CiteNexus.delete(document_id)`** (alias **`revoke`**) that surgically
  removes one document and everything it produced: its Evidence-Unit vector rows,
  its per-document image blobs and structure index, its etag-manifest entry, and —
  **guarded by a shared-content reference check** — its content-addressed raw blob;
  then it **rebuilds** the corpus-wide graph and **removes the document's wiki
  page(s)**, so navigation no longer points at deleted evidence. A `URL` form
  revokes a previously-crawled page by its document id.
- Add **`VectorStore.delete_document(document_id)`** to the storage seam (Lance +
  Postgres), a **`WikiStore.remove_document(document_id)`**, and manifest
  **`forget(document_id)`** / guarded **`clear_status(checksum)`**.
- **Raw-blob safety (the load-bearing invariant):** raw blobs are content-addressed
  and **not** refcounted, so two documents with identical bytes share one physical
  blob. A shared raw blob (and its slow-path queue/processing state, both keyed by
  checksum) is deleted **only** when no other document still owns that checksum.
- **Idempotent:** deleting an absent or already-deleted document is a no-op and
  returns a status (`deleted` vs `absent`); a double-delete never errors.
- **Resumable removal order:** derived artifacts are removed first and the
  etag-manifest entry (the ingest commit point) **last**, so a crash mid-delete
  re-runs cleanly and never leaves a document that is "half present."
- **Port parity:** the same `delete_document` threads through Go, JS, and the
  shared **Rust FFI store** (a new `citenexus_store_delete_document` C-ABI symbol
  wired into Go CGo + JS koffi), pinned by a `delete_roundtrip` conformance case so
  every port removes byte-for-byte the same rows.

## Capabilities

### New Capabilities
- `document-revoke`: the surgical, idempotent removal of one ingested document and
  all its derived artifacts (vector rows, image blobs, structure, manifest entry,
  guarded raw blob), the shared-raw-blob reference guard, the resumable
  manifest-last removal order, and the graph-rebuild + wiki-page-removal that keep
  navigation honest after a delete.

### Modified Capabilities
- `storage-partition-seam`: the `VectorStore` seam gains
  `delete_document(document_id)` (Lance + Postgres); the etag manifest gains an
  entry-removal operation. TextSearch needs no new method — it shares the rows.
- `ingest-pipeline`: ingest gains an inverse — undo a document's persisted
  artifacts and trigger graph rebuild + wiki page removal, in a resumable order.

## Impact

- **Specs:** new `document-revoke`; deltas on `storage-partition-seam` and
  `ingest-pipeline`. Reads on `provenance-and-rebuild`, `graph-retriever`,
  `wiki-navigation`, `worker-queue-resume`.
- **Code (Python reference):** `storage/protocols.py` (+`delete_document`),
  `storage/lance_store.py` + `storage/postgres_store.py` (impl),
  `storage/manifest.py` (+`forget`/`clear_status`), `wiki/store.py`
  (+`remove_document`), `client.py` (+`delete`/`revoke` + `on_delete` hook),
  reusing `StorageBackend.delete_prefix` for structure/image/raw and
  `GraphStore.build_from_store` for the graph rebuild.
- **Ports:** Go `VectorStore.DeleteDocument` + `core.Store`; JS `deleteDocument` +
  native store; Rust core `LanceStore.delete_document` + a new C-ABI symbol wired
  into Go CGo and JS koffi.
- **Conformance:** new `conformance/cases/delete_roundtrip.json`.
- **Docs:** add a `revoke` page and flip the "delete is absent" note in the
  published site once shipped.
