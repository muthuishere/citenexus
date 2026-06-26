## ADDED Requirements

### Requirement: Dense vector retriever

The library SHALL provide `VectorRetriever`, a concrete `RetrieverPlugin` that,
given a `LeafVectorStore` and an embedder exposing `embed(text) -> list[float]`,
embeds the query, calls `store.search(vector, limit=k)`, and maps each hit to a
`Candidate` with `signal = RetrievalSignal.vector`. It SHALL turn the vector
distance into a score that DESCENDS as distance grows (the nearest hit ranks
first), carry the hit's `eu_id`/`text`/`document_id`/`language`, and map the
ingest `page == -1` sentinel back to `None`. It SHALL carry a non-empty
`plugin_version`.

#### Scenario: Vector hits become vector-signal candidates ranked by similarity

- **WHEN** `retrieve(query, k)` runs against a seeded leaf store whose nearest
  row to the embedded query is `eu_a`
- **THEN** every returned candidate has `signal == RetrievalSignal.vector`, and
  `eu_a` is first with a score not lower than any later candidate's score

#### Scenario: Empty leaf yields no candidates

- **WHEN** `retrieve(query, k)` runs against a leaf store with no rows
- **THEN** the result is an empty list

### Requirement: Multilingual-safe lexical retriever

The library SHALL provide `LexicalRetriever`, a concrete `RetrieverPlugin` that
scores the texts from `LeafVectorStore.scan()` with a BM25-lite (idf×tf) ranking
over whitespace/punctuation tokenization, applying NO language-specific stemming
or stopword removal, and returns the top-k texts as `Candidate`s with
`signal = RetrievalSignal.lexical`. It SHALL carry a non-empty `plugin_version`.

#### Scenario: A term-matching document ranks first

- **WHEN** `retrieve("termination clause", k)` runs over a corpus where exactly
  one row contains the word "termination"
- **THEN** that row's candidate is first and every returned candidate has
  `signal == RetrievalSignal.lexical`

#### Scenario: Empty corpus yields no candidates

- **WHEN** `retrieve(query, k)` runs against a leaf store with no rows
- **THEN** the result is an empty list

### Requirement: Structure retriever resolves matching nodes to EUs

The library SHALL provide `StructureRetriever`, a concrete `RetrieverPlugin`
that, given a `StorageBackend` and a `PartitionPath`, reads the persisted
structure index json under `knowledge/<P>/structure/`, matches tokenized query
terms against each node's `label`, and returns the Evidence Units anchored under
matching nodes (the node and its descendants, resolved by `eu_ref` against the
store rows) as `Candidate`s with `signal = RetrievalSignal.structure`. When no
structure index exists for the partition, it SHALL return an empty list — a
normal outcome, not an error. It SHALL carry a non-empty `plugin_version`.

#### Scenario: Query term matching a heading returns the EUs under it

- **WHEN** `retrieve("termination", k)` runs against a partition whose structure
  index has a node labelled "Termination" anchoring `eu_t`
- **THEN** the result contains a candidate for `eu_t` with
  `signal == RetrievalSignal.structure`

#### Scenario: No structure index returns an empty list

- **WHEN** `retrieve("termination", k)` runs against a partition that has no
  structure index json
- **THEN** the result is an empty list

### Requirement: Reciprocal Rank Fusion by eu_id

The library SHALL provide `rrf_fuse(lists, k=60)`, a pure, deterministic function
that fuses ranked candidate lists by `eu_id` using Reciprocal Rank Fusion: each
candidate at zero-based `rank` in a list contributes `1 / (k + rank + 1)` to its
`eu_id`'s fused score. The fused candidate SHALL keep the best contributing
payload (the input candidate with the highest individual score) with its score
set to the fused score, and the result SHALL be ordered by descending fused score
with a deterministic tie-break. The default `k` SHALL be 60.

#### Scenario: An EU surfaced by two signals outranks one surfaced by a single signal

- **WHEN** `rrf_fuse([listA, listB])` fuses two lists where `eu_shared` appears
  in both and `eu_solo` appears at rank 0 of only one list
- **THEN** `eu_shared` ranks above `eu_solo` in the fused output

#### Scenario: Fusion is deterministic and respects k

- **WHEN** `rrf_fuse(lists, k=10)` and `rrf_fuse(lists, k=10)` are called on the
  same input
- **THEN** both return identical `eu_id` orderings, and a candidate's fused score
  equals the sum of `1/(10 + rank + 1)` over its appearances

### Requirement: OpenAI-compatible reranker over an injected transport

The library SHALL provide `OpenAICompatibleReranker`, a concrete
`RerankerPlugin` that reranks candidates by posting `{model, query, documents}`
to `{base_url}/rerank` through an injected
`transport: Callable[[str, bytes, dict[str, str]], bytes]`, reordering the input
candidates by the endpoint's per-document relevance scores. When no transport is
supplied the default SHALL use the Python standard library (`urllib.request`) and
add no third-party dependency. It SHALL carry a non-empty `plugin_version`.

#### Scenario: A fake transport reorders candidates by returned relevance

- **WHEN** the reranker is constructed with a fake transport that returns
  `{"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0,
  "relevance_score": 0.1}]}` for two input candidates
- **THEN** `rerank(query, [c0, c1])` returns `[c1, c0]` and performs no network IO

### Requirement: Retrieval engine fuses, reranks, and returns ranked EUs

The library SHALL provide `RetrievalEngine`, constructed from a set of
retrievers and an injected reranker, exposing `retrieve(query, k) ->
list[Candidate]`. It SHALL run each retriever for the query, fuse the lists with
`rrf_fuse`, rerank the fused top-N through the injected reranker, and return the
ranked candidates (already EU-native; navigate-not-cite is a no-op for the
vector/lexical/structure signals). With an identity reranker the engine SHALL
preserve the fused order.

#### Scenario: End-to-end retrieval returns a fused, reranked, ranked list

- **WHEN** `retrieve(query, k)` runs over a seeded store with the vector,
  lexical, and structure retrievers and an identity reranker
- **THEN** the reranker seam is invoked and the result is a non-empty list of
  `Candidate`s in the fused order, capped at `k`
