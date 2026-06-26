## 1. Tests first (red)

- [ ] 1.1 Create `tests/retrieve/__init__.py` and shared seeding helpers (a
  local `LeafVectorStore` upserted with `FakeEmbedding` rows; a `LocalFsBackend`
  with a structure index json).
- [ ] 1.2 Write `test_vector.py` — vector-signal candidates, similarity order,
  empty leaf ⇒ `[]`.
- [ ] 1.3 Write `test_lexical.py` — lexical-signal, a term-matching doc first,
  empty corpus ⇒ `[]`.
- [ ] 1.4 Write `test_structure.py` — EUs under a matching heading, `[]` when no
  index.
- [ ] 1.5 Write `test_fusion.py` — two-signal EU outranks single-signal; RRF
  score math; determinism; `k` respected.
- [ ] 1.6 Write `test_rerank.py` — fake transport reorders by relevance, no IO.
- [ ] 1.7 Write `test_engine.py` — end-to-end fused+reranked list; reranker seam
  invoked; identity keeps order.

## 2. Retrievers (green)

- [ ] 2.1 Implement `retrieve/vector.py` — `VectorRetriever(RetrieverPlugin)`.
- [ ] 2.2 Implement `retrieve/lexical.py` — `LexicalRetriever(RetrieverPlugin)`
  BM25-lite, multilingual-safe.
- [ ] 2.3 Implement `retrieve/structure.py` — `StructureRetriever(RetrieverPlugin)`.

## 3. Fusion, rerank, engine

- [ ] 3.1 Implement `retrieve/fusion.py` — `rrf_fuse(lists, k=60)` (pure,
  deterministic).
- [ ] 3.2 Implement `retrieve/rerank.py` — `OpenAICompatibleReranker`
  (injected transport, stdlib default; integration-only).
- [ ] 3.3 Implement `retrieve/engine.py` — `RetrievalEngine.retrieve(query, k)`.

## 4. Verify

- [ ] 4.1 `uv run pytest tests/retrieve -m "not integration" -q` green.
- [ ] 4.2 `uv run ruff check src/trustrag/retrieve tests/retrieve` clean.
- [ ] 4.3 `uv run mypy src/trustrag/retrieve tests/retrieve` clean.
- [ ] 4.4 `openspec validate retrieve-engine --strict` passes.
