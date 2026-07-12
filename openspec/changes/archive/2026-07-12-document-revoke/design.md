# Design — document-revoke

## Write-path inventory (what delete must undo)

A single `ingest()` (`ingest/pipeline.py`) persists, per partition `<P>`:

| # | Artifact | Key / location | Keyed by | Per-doc? |
|---|----------|----------------|----------|----------|
| a | Raw blob | `raw/<P>/{checksum}` | **checksum** (content-addressed) | **NO — shared by identical bytes** |
| b | Image blobs | `raw/<P>/images/{document_id}/{image_id}` | document_id | yes |
| c | Vector rows | Lance `evidence_units` (`vector/<P>/lancedb`) | eu_id; rows carry `document_id`, `checksum`, `raw_uri` | filterable by `document_id` |
| d | Structure index | `knowledge/<P>/structure/{document_id}.json` | document_id | yes |
| e | Etag manifest entry | `manifests/<P>/etag_manifest.json` → `etags[document_id] = checksum` | document_id | entry per doc |
| f | Slow-path queue job | durable queue `enqueue(checksum, …)` | **checksum** | payload has doc_id |
| g | Graph artifact | `graph/<P>/graph.json` | corpus-wide co-mention | **NO — whole-leaf** |
| h | Wiki artifacts | `knowledge/<P>/wiki/pages/{slug}.{json,md}` + shared `index.json`/`index.md`/`log.md` | page slug (== document_id in the deterministic path) | page per-doc; index/log shared |

## Key decisions

### 1. Raw blob is content-addressed and NOT refcounted (highest risk)
`raw/<P>/{sha256}` is written idempotently (`put_blob` skips if the key exists).
Two documents with identical bytes but different `document_id` both pass
`is_changed` (etag keyed by doc_id) and share **one** physical blob — no refcount
anywhere. Surviving documents' vector rows still carry `raw_uri` at that key.

**Decision:** delete the raw blob **only after a reference check** — no other
`etags` entry maps to the same checksum **and** no remaining vector row carries
that checksum (cheap: scan `EtagManifest.etags.values()` and/or `store.scan()`
after the row delete). Chosen over a new `blob_refs.json` refcount manifest, which
adds standing state to keep consistent. The same shared-checksum guard governs the
slow-path queue job (f) and `ProcessingManifest` status (both checksum-keyed):
do not cancel/forget the checksum's slow-path state if another document owns it.

### 2. New storage-seam method: `delete_document(document_id)`, not `delete(predicate)`
A raw predicate string leaks Lance-vs-SQL syntax across backends and invites
injection. Add one narrow method to the `VectorStore` protocol:
- Lance: `tbl.delete("document_id = '<escaped>'")`, guarded like `search` for a
  missing table.
- Postgres: `DELETE FROM {table} WHERE document_id = %s` (parameterized), tolerant
  of a missing table.
- TextSearch: **no new method** — Lance BM25 is in-core over `scan()`, and Postgres
  text search shares the same leaf table; the row delete covers both.

### 3. Manifests
`EtagManifest.forget(document_id)` = `etags.pop(document_id, None)` + persist.
`ProcessingManifest.clear_status(checksum)` = `status.pop(checksum, None)` — called
**only** when no other document owns the checksum (§1). Confirm the persisted
`ProcessingManifest` filename in `worker/executor.py` before wiring `clear_status`.

### 4. Structure / image / raw blobs
Reuse existing `StorageBackend.delete_prefix` — structure file, `images/{doc}/`
prefix (safe, per-doc namespaced), and the raw blob key (only after §1 guard).

### 5. Graph is whole-leaf → rebuild after delete
`graph.json` is corpus-wide co-mention; there is no per-document edit. After the
rows are gone, rebuild via `GraphStore.build_from_store(store)` (exactly what
ingest's `_refresh_incremental` does). Only when the `graph`/`community` signal is
declared.

### 6. Wiki → add `WikiStore.remove_document(document_id)`
No per-page delete exists today (only `save()` = delete-all-then-rewrite, and
`integrate_document` = upsert-one). Add a cheap remover: `delete_prefix` the page
`.json`/`.md` for that slug, rewrite `index.json`/`index.md` from the remaining
`load_index()` entries, append a `delete | {id}` line to `log.md`. Avoids
re-running the LLM distiller over the whole corpus. Only when `wiki` is declared.

### 7. Idempotent double-delete + return status
Every remover is a no-op on absent state (`dict.pop(…, None)`, 0-match predicate,
`delete_prefix` on a missing key already no-ops). `delete()` returns a small
`DeleteResult` with `status` (`"deleted"` when the document existed, `"absent"`
otherwise) and the removed `eu_ids` count.

### 8. Resumable removal order (no cross-store atomicity)
S3 + Lance/Postgres + manifest are separate stores; a partial failure orphans
artifacts. Ingest writes the etag manifest **last** as its commit point. Delete
mirrors this: remove derived artifacts first (rows → structure → images → guarded
raw/graph/wiki), then `forget()` the manifest entry **last**. A crash before the
manifest write leaves the document "still logically present," so a re-run
re-deletes cleanly and idempotently. Document this order as the contract.

### 9. In-flight slow-path job
A queued job (checksum-keyed) may still be running when delete lands; its later
graph/wiki write could resurrect artifacts. Sequence delete **after** — or cancel —
the checksum's slow-path state, again respecting shared-checksum ownership (§1).

## Port-parity surface
- **Go** (`golang/storage`, `golang/core`): add `DeleteDocument(documentID string) error`
  to the `VectorStore` interface + `core.Store`; impl in `lance_adapter.go`,
  `postgres_store.go`.
- **JS** (`js/src/storage`, `js/src/core`): add `deleteDocument(documentId): Promise<void>`
  to `VectorStore` + the native `Store`; impl in `postgres.ts` + koffi symbol.
- **Rust core** (`rust/src/store.rs`, `ffi.rs`, `lib.rs`): add
  `LanceStore.delete_document(&self, document_id: &str)` via `table.delete(predicate)`;
  expose `citenexus_store_delete_document` C-ABI symbol; wire into Go CGo + JS koffi.

## Conformance
New `conformance/cases/delete_roundtrip.json` (alongside `e2e_hermetic.json`):
ingest N documents → `delete` one → assert its EUs/citations vanish, survivors are
intact and still answerable, and a second delete of the same id is a no-op. Every
port's conformance runner exercises it.
