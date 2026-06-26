## Why

The §4b `RetrieverPlugin` / `RerankerPlugin` protocols and the shared `Candidate`
type exist, and the leaf vector store can now `search` and `scan`, but nothing
turns a query into ranked candidates: there is no retriever, no fusion, no
rerank, and no engine to wire them. This change lands the v0.1 retrieval layer —
the three foundational signals (vector, lexical, structure), Reciprocal Rank
Fusion, the rerank seam, and the `RetrievalEngine` that orchestrates them — so
L5 answer-flow has fused, reranked EUs to ground on.

## What Changes

- Add `VectorRetriever(RetrieverPlugin)` — embeds the query with an injected
  embedder, calls `LeafVectorStore.search`, and maps each hit to a
  `Candidate(signal=vector)` whose score descends as the vector distance grows.
- Add `LexicalRetriever(RetrieverPlugin)` — a multilingual-safe BM25-lite
  (idf×tf, no language-specific stemming) over `LeafVectorStore.scan()` texts,
  emitting `Candidate(signal=lexical)`. This is the v0.1 sparse/lexical signal;
  real BGE-M3 learned-sparse weights are a future upgrade (see design.md).
- Add `StructureRetriever(RetrieverPlugin)` — reads the persisted structure index
  json (`knowledge/<P>/structure/<doc>.json`) for a partition, matches query
  terms against node labels, and returns the EUs anchored under matching nodes as
  `Candidate(signal=structure)`. No structure index ⇒ `[]` (normal, not an error).
- Add `rrf_fuse(lists, k=60)` — pure, deterministic Reciprocal Rank Fusion by
  `eu_id` (sum of `1/(k+rank)`), keeping the best contributing payload and
  returning candidates in descending fused-score order.
- Add `OpenAICompatibleReranker(RerankerPlugin)` — reorders fused candidates via
  an injected transport (stdlib `urllib` default; integration-only). Hermetic
  tests use the existing `FakeReranker` (identity).
- Add `RetrievalEngine` — runs each retriever, fuses with RRF, reranks the fused
  top-N through the injected reranker, and returns ranked `Candidate`s.
  Navigate-not-cite (§10b) is a no-op for these three EU-native signals; graph /
  community / wiki resolve-down lands later.

## Capabilities

### New Capabilities
- `retrieve-engine`: the v0.1 retrieval layer — the vector / lexical / structure
  retrievers, RRF fusion, the rerank seam, and the orchestrating
  `RetrievalEngine.retrieve(query, k)`.

### Modified Capabilities
<!-- none — the RetrieverPlugin / RerankerPlugin protocols and the shared
     Candidate type already exist (plugin-protocol-registry, core-domain-types);
     this change supplies the first concrete retrievers, fusion, and engine. -->

## Impact

- New modules under `src/trustrag/retrieve/` (`vector.py`, `lexical.py`,
  `structure.py`, `fusion.py`, `rerank.py`, `engine.py`); `__init__.py` and
  `types.py` are untouched (exports wired separately).
- New tests under `tests/retrieve/`.
- No new dependencies — stdlib only (`urllib` for the integration reranker).
  No `pyproject.toml` change.
