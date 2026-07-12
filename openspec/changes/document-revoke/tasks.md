## 1. Storage seam — `delete_document` (red → green)

- [ ] 1.1 Write a failing test: `VectorStore.delete_document(document_id)` removes all rows for that document and leaves other documents' rows intact (LanceVectorStore, temp dir)
- [ ] 1.2 Write a failing test: `delete_document` on an unknown/empty document_id is a no-op (no error, no rows removed); on a missing table it is a no-op
- [ ] 1.3 Add `delete_document(self, document_id: str) -> None` to the `VectorStore` Protocol (`storage/protocols.py`); implement in `LanceVectorStore` (`tbl.delete("document_id = '<escaped>'")`, guard missing table) — make 1.1–1.2 green
- [ ] 1.4 Implement `delete_document` in `PostgresVectorStore` (parameterized `DELETE … WHERE document_id = %s`, tolerate missing table); test against the pg-backed store (marked integration where needed)
- [ ] 1.5 Assert the in-core BM25 / TextSearch reflects the deletion automatically (no separate method) — a lexical query for the deleted doc's terms returns none of its EUs

## 2. Manifest removal (red → green)

- [ ] 2.1 Write a failing test: `EtagManifest.forget(document_id)` removes the entry and persists; a second `forget` is a no-op
- [ ] 2.2 Add `EtagManifest.forget()` and `ProcessingManifest.clear_status(checksum)` (`storage/manifest.py`); make 2.1 green
- [ ] 2.3 Confirm the persisted `ProcessingManifest` name/arg in `worker/executor.py` and cover `clear_status` persistence

## 3. Wiki per-document removal (red → green)

- [ ] 3.1 Write a failing test: `WikiStore.remove_document(document_id)` deletes that page's `.json`/`.md`, rewrites `index.json`/`index.md` without the stale entry, and appends a `delete | {id}` log line; survivors' pages remain
- [ ] 3.2 Implement `WikiStore.remove_document` (`wiki/store.py`) reusing the index-writing tail; make 3.1 green

## 4. Client orchestration — `CiteNexus.delete` / `revoke` (red → green)

- [ ] 4.1 Write a failing test: after `ingest("nda")` + `ingest("leave")`, `rag.delete("nda")` makes `ask()` no longer retrieve/cite `nda`, while `leave` is still answerable
- [ ] 4.2 Write a failing test: the removal ORDER is resumable — derived artifacts (rows, structure, images, guarded raw/graph/wiki) removed before the etag-manifest entry (commit point) last
- [ ] 4.3 Add `CiteNexus.delete(document_id)` + `revoke` alias returning a `DeleteResult(status, removed_eu_ids)`; orchestrate rows → structure/image `delete_prefix` → guarded raw → graph rebuild → wiki `remove_document` → `manifest.forget` last; fire an `on_delete` hook (mirror `on_ingest`). Make 4.1–4.2 green
- [ ] 4.4 Wire graph rebuild only when `graph`/`community` declared, wiki removal only when `wiki` declared

## 5. Raw-blob reference guard + idempotency (red → green)

- [ ] 5.1 Write a failing test (the load-bearing one): ingest two documents with **identical bytes** (shared checksum, different document_id); `delete` one → the raw blob `raw/<P>/{checksum}` SURVIVES and the other document is still answerable with intact `raw_uri`
- [ ] 5.2 Write a failing test: delete the last owner of a checksum → the raw blob IS removed; the checksum's queue/`ProcessingManifest` state is cleared only then
- [ ] 5.3 Write a failing test: `delete` of an absent/already-deleted document returns `status="absent"` and does not error (double-delete safe)
- [ ] 5.4 Implement the reference check (scan `etags.values()` + post-delete `store.scan()` for the checksum) and the idempotent return status; make 5.1–5.3 green

## 6. Conformance fixture (the parity pin)

- [ ] 6.1 Add `conformance/cases/delete_roundtrip.json`: ingest N docs → delete one → expected surviving EUs/citations + a double-delete no-op
- [ ] 6.2 Wire the Python conformance runner to exercise it

## 7. Rust FFI store — the shared reference backend

- [ ] 7.1 Add `LanceStore.delete_document(&self, document_id: &str)` (`rust/src/store.rs`) via `table.delete(predicate)`; unit test round-trip
- [ ] 7.2 Expose `citenexus_store_delete_document` C-ABI symbol (`rust/src/ffi.rs`), re-export (`lib.rs`); `cargo test`

## 8. Go parity (red → green)

- [ ] 8.1 Write a failing Go test mirroring the conformance case; add `DeleteDocument(documentID string) error` to the `VectorStore` interface (`golang/storage/storage.go`) + `core.Store` (`golang/core/core.go`, new FFI symbol)
- [ ] 8.2 Implement in `lance_adapter.go` (FFI) + `postgres_store.go`; make the Go conformance runner pass `delete_roundtrip`

## 9. JS parity (red → green)

- [ ] 9.1 Write a failing vitest mirroring the conformance case; add `deleteDocument(documentId): Promise<void>` to `VectorStore` (`js/src/storage/protocols.ts`) + native `Store` (`js/src/core/core.ts`, koffi symbol)
- [ ] 9.2 Implement in `js/src/storage/postgres.ts` + the native store; make the JS conformance runner pass `delete_roundtrip`

## 10. Docs (after green)

- [ ] 10.1 Add a `revoke` docs page (delete/revoke a document or crawled page; idempotency; what is removed; the shared-blob guarantee)
- [ ] 10.2 Flip the "delete is absent" note in `bulk-ingest.mdx` and the capability memory; mention `delete()` on `ingest`/`file-based`/`s3` pages
- [ ] 10.3 `task check` (lint + mypy over src+tests) green; ports CI green
