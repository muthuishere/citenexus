# Design — retrieve-engine (§10 retrieval + RRF fusion + rerank)

## Seam recap

Every retriever subclasses `RetrieverPlugin` and returns a ranked
`list[Candidate]` (the shared, frozen type in `retrieve/types.py`). A retriever
*only* ranks — it never fuses, reranks, or grounds. Fusion (`rrf_fuse`) and the
engine stay in core so a third-party retriever can't bypass the RRF + grounding
guarantees (§4b). The shared `Candidate` and `RetrievalSignal` are imported, not
redefined; `retrieve/__init__.py` and `retrieve/types.py` are not edited here.

## The three v0.1 signals

### Vector (dense)
`VectorRetriever(store, embedder)` embeds the query (`embedder.embed(text) ->
list[float]`, satisfied by `FakeEmbedding` in tests), calls
`store.search(vec, limit=k)`, and maps each hit to
`Candidate(signal=vector)`. LanceDB returns a `_distance` per hit (lower = more
similar); we turn distance into a **descending** score via `1/(1+distance)` so
the nearest hit ranks first and ties are stable. Stored `page == -1` (the
ingest sentinel for "no page") maps back to `None`.

### Lexical (sparse) — BM25-lite, multilingual-safe
`LexicalRetriever(store)` scans every row's text once (`store.scan()`),
tokenizes with `citenexus.testing.fakes.tokenize` (lowercase `[a-z0-9]+`, NO
stemming, NO stopwords — language-agnostic so it never penalizes non-English
text), and scores each document with classic BM25 (`k1=1.5`, `b=0.75`):
`score = Σ_t idf(t)·tf'`, `idf(t)=ln(1+(N−n_t+0.5)/(n_t+0.5))`. A document that
contains a query term outranks one that does not. Returns the top-k by score.

> **Honest scope:** this is a lexical *bag-of-terms* signal, not BGE-M3's learned
> sparse weights. Real sparse retrieval needs a sparse-capable embedding endpoint
> and is a future upgrade; BM25-lite is the deterministic, hermetic v0.1 stand-in
> and is exactly what proves the fusion property offline.

### Structure
`StructureRetriever(backend, partition, store)` lists
`knowledge/<P>/structure/*.json` (`<P>` from `layer_prefix(Layer.knowledge, …)`),
loads each `StructureIndex`, and matches tokenized query terms against each
node's `label`. For every matched node it collects the EUs anchored by that node
**and its descendants** (`eu_ref`, which is `document_id::order` — the same id
the store rows carry as `eu_id`), resolves them against `store.scan()`, and emits
`Candidate(signal=structure)` scored by how many query terms matched the node
label. If no structure index exists for the partition (the `structure` signal was
never ingested, or every document degraded to zero nodes), it returns `[]` — a
normal outcome per §7b, never an error.

## RRF fusion
`rrf_fuse(lists, k=60)` is pure and deterministic. For each input list it walks
candidates in rank order (rank 0 = first) and adds `1/(k+rank+1)` to that
`eu_id`'s fused score. The fused candidate keeps the **best contributing
payload** (the input candidate with the highest individual score; first
occurrence breaks ties) with its score replaced by the fused score. Output is
sorted by `(−fused_score, eu_id)` so order is total and deterministic. The key
property: an EU surfaced by two signals (two `1/(k+rank)` terms) outranks an EU
surfaced by only one, even from rank 0 — this is what makes multi-signal
agreement win.

## Rerank seam
`OpenAICompatibleReranker(RerankerPlugin)` posts `{model, query, documents}` to
`{base_url}/rerank` through an **injected** `transport` (default: stdlib
`urllib.request`, so no new dependency) and reorders candidates by the returned
per-document relevance scores. It is integration-only (`@pytest.mark.integration`)
because it talks to a real endpoint. Hermetic tests use the existing
`FakeReranker`, whose `rerank` is `list(candidates)` — a generic identity over
*any* list, so it preserves the fused order regardless of element type.

## Engine
`RetrievalEngine(retrievers, reranker, *, rrf_k=60, rerank_top_n=50)` runs each
retriever for the query, `rrf_fuse`s the lists, reranks the fused top-N through
the injected reranker, appends the un-reranked tail, and returns the first `k`.
The reranker is typed structurally (a tiny `Protocol` with `rerank(query,
candidates)`) so both `RerankerPlugin` implementations and the looser
`FakeReranker` satisfy it. Navigate-not-cite is a no-op here: all three signals
already produce EU-native candidates.

## Why these choices
- **`1/(1+distance)`** keeps vector scores positive, bounded, and strictly
  descending in distance without assuming a distance metric range.
- **BM25 over plain tf-idf** gives length normalization for free and is the
  industry-standard lexical baseline; "lite" = no stemming/stopwords for
  multilingual safety.
- **Best-payload-wins on fusion** means the surviving `Candidate` always carries
  real `text`/`document_id`/`page` for citation without a second store round-trip.
