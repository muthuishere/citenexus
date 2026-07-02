## 1. Result + pipeline (test-first)

- [ ] 1.1 Failing tests `tests/ingest/test_pipeline.py`: raw-text ingest yields
      EUs with language; unknown→plain; idempotent re-ingest (`unchanged`);
      signal gating (embedding/text upserts; structure persists; slow-path
      enqueues); IngestResult reports eu_ids/n_units.
- [ ] 1.2 Implement `src/citenexus/ingest/result.py` (`IngestResult`).
- [ ] 1.3 Implement `src/citenexus/ingest/pipeline.py` (`IngestPipeline`,
      `Embedder` protocol) wiring dispatch→detect→build→structure→embed→storage,
      signal-gated + idempotent.

## 2. Integration + gate

- [ ] 2.1 `@pytest.mark.integration` variant ingests a file over MinIO.
- [ ] 2.2 Scoped ruff + mypy + pytest on ingest — green.
- [ ] 2.3 `openspec validate ingest-pipeline` valid.
