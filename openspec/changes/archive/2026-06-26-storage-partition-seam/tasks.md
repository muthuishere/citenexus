## 1. Partition prefixes (test-first)

- [ ] 1.1 Failing tests `tests/storage/test_paths.py`: `<P>` encoding + the seven
      layer prefixes, for 1- and 3-level paths.
- [ ] 1.2 Implement `src/trustrag/storage/paths.py`.

## 2. Backend seam (test-first, hermetic on LocalFs)

- [ ] 2.1 Failing tests `tests/storage/test_backend.py`: bytes round-trip,
      content-addressed `put_blob` dedup, json round-trip, `delete_prefix`,
      `list_prefix` — run against `LocalFsBackend`.
- [ ] 2.2 Implement `src/trustrag/storage/backend.py` (`StorageBackend`,
      `LocalFsBackend`, `S3Backend`).

## 3. Leaf vector store (test-first, hermetic on local lance path)

- [ ] 3.1 Failing tests `tests/storage/test_lance_store.py`: upsert+search,
      two-leaf isolation, drop-leaf — on a `tmp_path` local LanceDB.
- [ ] 3.2 Implement `src/trustrag/storage/lance_store.py`.

## 4. Manifests (test-first)

- [ ] 4.1 Failing tests `tests/storage/test_manifest.py`: etag unchanged/dirty,
      model & processing manifest round-trip via a backend.
- [ ] 4.2 Implement `src/trustrag/storage/manifest.py`.

## 5. Integration (opt-in, against compose MinIO)

- [ ] 5.1 `tests/storage/test_integration_minio.py` marked
      `@pytest.mark.integration`: the SAME backend + lance contract over
      `S3Backend` and `s3://…` LanceDB against `http://localhost:19000`.

## 6. Gate

- [ ] 6.1 Scoped: `uv run pytest tests/storage -m "not integration"`, `ruff`,
      `mypy` on `src/trustrag/storage tests/storage` — all green.
- [ ] 6.2 `openspec validate storage-partition-seam` is valid.
