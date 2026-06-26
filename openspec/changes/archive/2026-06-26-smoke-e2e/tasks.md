## 1. Fakes (test-first)

- [x] 1.1 `tests/e2e` exercises the fakes via the pipeline.
- [x] 1.2 Implement `src/trustrag/testing/fakes.py` (`FakeEmbedding`, `FakeLLM`,
      `FakeReranker`, `tokenize`) + `__init__.py`.

## 2. Pipeline (test-first)

- [x] 2.1 Failing tests `tests/e2e/test_smoke.py`: answer-cites-evidence,
      abstain-on-empty, retrieves-the-right-doc.
- [x] 2.2 Implement `src/trustrag/smoke/pipeline.py` (`SmokePipeline`,
      `Embedder`/`Generator` protocols, faithfulness gate, cite-or-abstain).

## 3. Integration + gate

- [x] 3.1 `@pytest.mark.integration` variant runs the same path over MinIO.
- [x] 3.2 Scoped ruff + mypy + pytest on smoke/testing/e2e — green.
