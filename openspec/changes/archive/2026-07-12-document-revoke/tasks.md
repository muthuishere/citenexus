> **Status (Phase 2 apply):** Python reference + Rust/Go/JS store parity + docs
> are implemented and green. The cross-language **conformance fixture**
> (`delete_roundtrip.json`, §6) and the port **conformance runners** wiring
> (§8.2/§9.2 tails) are the only deferred items — store-level parity is already
> proven by per-language native tests (`tests/store_test.rs`,
> `core_test.go:TestStoreDeleteDocument`, `core.test.ts` deleteDocument).

## 1. Storage seam — `delete_document` (red → green)

- [x] 1.1 Failing test: `VectorStore.delete_document` removes a document's rows, leaves others (LanceVectorStore, temp dir) — `tests/storage/test_delete_document.py`
- [x] 1.2 Failing test: `delete_document` on unknown id / missing table is a no-op
- [x] 1.3 Add `delete_document` to the `VectorStore` Protocol; implement in `LanceVectorStore` (`tbl.delete`, quote-escaped, guarded missing table)
- [x] 1.4 Implement `delete_document` in `PostgresVectorStore` (parameterized `DELETE … WHERE document_id = %s`, tolerant of missing table) — integration-gated
- [x] 1.5 Lexical (BM25) reflects the deletion automatically — covered by `test_lexical_index_reflects_deletion`

## 2. Manifest removal (red → green)

- [x] 2.1 Failing test: `EtagManifest.forget` removes + is idempotent; `owners_of` is the shared-blob refcount — `tests/storage/test_manifest.py`
- [x] 2.2 Add `EtagManifest.forget()` + `owners_of()` and `ProcessingManifest.clear_status()`
- [~] 2.3 `clear_status` unit-tested; NOT wired into the client — the reference client persists no JSON `ProcessingManifest` (the durable queue is SQLite and unwired), so there is no slow-path JSON state to clear in the default flow

## 3. Wiki per-document removal (red → green)

- [x] 3.1 Failing test: `WikiStore.remove_document` deletes the page `.json`/`.md`, rewrites `index.json`/`index.md`, logs a `delete` line; survivors remain — `tests/wiki/test_remove_document.py`
- [x] 3.2 Implement `WikiStore.remove_document`

## 4. Client orchestration — `CiteNexus.delete` / `revoke` (red → green)

- [x] 4.1 Failing test: after two ingests, `rag.delete(one)` makes `ask()` no longer retrieve/cite it; the other stays answerable — `tests/test_client_delete.py`
- [x] 4.2 Failing test: removal order is resumable — derived artifacts before the etag-manifest entry (commit point) last
- [x] 4.3 Add `CiteNexus.delete` + `revoke` alias returning `DeleteResult(status, removed_eu_ids)`; orchestrate rows → structure/images → guarded raw → graph rebuild → wiki `remove_document` → `manifest.forget` last; fire `on_delete`
- [x] 4.4 Graph rebuild only when `graph`/`community` declared; wiki removal only when `wiki` declared

## 5. Raw-blob reference guard + idempotency (red → green)

- [x] 5.1 Failing test (load-bearing): two documents with identical bytes; `delete` one → the shared raw blob SURVIVES, the twin stays answerable with intact `raw_uri`
- [x] 5.2 Failing test: delete the last owner → the raw blob IS removed (queue/ProcessingManifest clearing N/A in the reference client — unwired)
- [x] 5.3 Failing test: `delete` of absent/already-deleted returns `status="absent"`, no error
- [x] 5.4 Implement the reference check via `EtagManifest.owners_of(checksum, excluding=id)` + idempotent status

## 6. Conformance fixture (the parity pin) — DEFERRED

- [ ] 6.1 Add `conformance/cases/delete_roundtrip.json`: upsert N docs → delete one → expected surviving rows + double-delete no-op (requires extending `scripts/gen_conformance.py`; `test_no_orphan_fixture_files` enforces committed == generated)
- [ ] 6.2 Wire the Python conformance runner to exercise it

## 7. Rust FFI store — the shared reference backend

- [x] 7.1 `LanceStore::delete_document(&self, document_id)` (`rust/src/store.rs`) via `table.delete(predicate)`; test round-trip — `tests/store_test.rs::delete_document_removes_only_that_documents_rows` (8 passed)
- [x] 7.2 `citenexus_store_delete_document` C-ABI symbol (`rust/src/ffi.rs`); exported via `pub mod ffi`; `cargo build --release` confirms the symbol

## 8. Go parity (red → green)

- [x] 8.1 `DeleteDocument(documentID string) error` on the `VectorStore` interface (`storage/storage.go`) + `core.Store` (new FFI decl + method); FFI test `core_test.go::TestStoreDeleteDocument` (green through CGo→Rust→LanceDB)
- [x] 8.2 Implemented in `lance_adapter.go` (FFI) + `postgres_store.go`; `go build -tags citenexus_ffi ./...` OK (interface satisfied). Conformance-runner wiring waits on §6.

## 9. JS parity (red → green)

- [x] 9.1 `deleteDocument(documentId): Promise<void>` on `VectorStore` (`js/src/storage/protocols.ts`) + native `Store.deleteDocument` (koffi symbol); vitest `core.test.ts` deleteDocument case (16 passed); `tsc --noEmit` clean
- [x] 9.2 Implemented in `js/src/storage/postgres.ts` + the native store. Conformance-runner wiring waits on §6.

## 10. Docs (after green)

- [x] 10.1 New `revoke.mdx` page (delete/revoke, idempotency, what's removed, the shared-blob guarantee, resumable order, port parity); added to the sidebar
- [x] 10.2 No stale "delete is absent" note existed to flip; added a `delete()` pointer on `ingest.mdx`; capability memory updated
- [x] 10.3 Python `task check` equivalent green (ruff + mypy `--strict` + 594 pytest); Rust/Go/JS port tests green locally
