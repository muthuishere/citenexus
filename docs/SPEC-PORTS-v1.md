# TrustRAG Language-Port Specification v1 — Go & TypeScript

> One contract, three languages. Python is the **reference implementation**;
> ports conform to this contract, not to Python's source. Discipline borrowed
> from toolnexus: shared spec, per-language idiom, byte-identical behavior
> where behavior is observable.

## 0. The one invariant that makes ports cheap

**All state lives in S3 (or a filesystem) in language-neutral formats.**
Raw blobs are content-addressed bytes; manifests, graph, and wiki artifacts are
JSON; the vector index is **Lance format** (Arrow-based, readable natively from
Rust, Python, and TypeScript). There is no server, no wire protocol, no
process-local state.

Therefore the port contract is: **a corpus ingested by any implementation must
be retrievable and answerable by every other implementation, byte-for-byte.**
Python ingests → Go asks → TS evaluates, against the same bucket. Every rule in
this spec exists to protect that sentence.

## 1. Conformance tiers

Ports declare a tier; CI runs the shared conformance suite (§10) per tier.

| Tier | Capabilities | Required for |
|---|---|---|
| **T1 — Core** | client construct/from-config · `ingest` (text/bytes/path) · `retrieve` · `ask` (strict cite-or-abstain) · `evaluate(csv)` · Lance + Postgres backends · hooks · telemetry sink · streaming (post-verification chunking) · EN dual-query RRF | first release of any port |
| **T2 — Breadth** | extractors beyond txt/md/html (pdf/docx/pptx/csv) · chunker + contextualizer · graph/wiki/memory signals · web crawl · vision-into-evidence | parity release |
| **T3 — Later** | worker queue/DLQ · MCP · judge | optional |

A port MUST NOT ship an `ask()` without the faithfulness gate. A partial port
that answers without verifying is worse than no port — it carries the brand
without the guarantee.

## 2. Public API contract

Method names follow each language's idiom; **semantics and defaults are fixed**.

| Concept | Python (reference) | Go | TypeScript |
|---|---|---|---|
| Construct | `TrustRAG(base_uri, embedder=…, generator=…)` | `trustrag.New(baseURI, trustrag.WithEmbedder(…), …)` | `new TrustRAG(baseUri, { embedder, generator })` |
| From config | `TrustRAG.from_config(cfg)` | `trustrag.FromConfig(cfg)` | `TrustRAG.fromConfig(cfg)` |
| Ingest | `ingest(source, text=, document_id=, acl=)` | `Ingest(ctx, src, …opts)` | `await ingest(source, opts)` |
| Retrieve | `retrieve(q, k=, conversation_id=)` | `Retrieve(ctx, q, …)` | `await retrieve(q, opts)` |
| Ask | `ask(q, mode=, answer_language=, conversation_id=)` | `Ask(ctx, q, …)` | `await ask(q, opts)` |
| Stream | `stream(q, …)` → chunks | `Stream(ctx, q, …)` → channel | `stream(q)` → async iterable |
| Evaluate | `evaluate(csv_path)` | `Evaluate(ctx, path)` | `await evaluate(path)` |
| Crawl (T2) | `crawl(seed, max_pages=50, max_depth=3)` | `Crawl(ctx, seed, …)` | `await crawl(seed, opts)` |

Fixed defaults everywhere: `top_k=5`, strict trust mode, `memory_max_turns=20`,
`default_answer_language="en"`, partition `workspace=default`.

Go note: errors return `error`; a refusal is **not** an error — it is a valid
`Result` with `decision=refused`. TS note: everything IO-bearing is async.

## 3. Storage contract (the interop layer)

### 3.1 Layout — MUST be byte-identical

```
{base}/raw/{P}/{sha256-of-raw-bytes}            content-addressed raw blob
{base}/manifests/{P}/etag_manifest.json         idempotency (doc_id → checksum)
{base}/knowledge/{P}/structure/{doc_id}.json    structure index
{base}/knowledge/{P}/wiki/pages.json            wiki artifact (T2)
{base}/graph/{P}/graph.json                     graph artifact (T2)
{base}/vector/{P}/lancedb/                      Lance database (one per leaf)
```

- `{P}` = `level=value/level=value/…` joined with `/` (e.g. `org=acme/product=x`).
- Layer names are the closed set: `raw extracted knowledge graph vector manifests eval`.
- Checksums: **SHA-256 hex, lowercase** of the raw source bytes.
- Lance table name: `evidence_units`, one table per leaf database.

### 3.2 Row schema — MUST be identical

Every EU row (Lance column set == Postgres column set == dict keys):

```
eu_id: string    vector: float32[]   text: string      document_id: string
language: string page: int (−1 = none)  checksum: string  raw_uri: string
```

Search results add `_distance` (cosine); text-search results add `_text_score`.

### 3.3 The two store protocols

```
VectorStore:  upsert(rows) · search(vector, limit) -> rows+_distance · scan(limit?)
TextSearch:   search_text(query, limit) -> rows+_text_score        (optional)
```

Backend pairs (names are part of the contract):

| Backend | Vector | Text | Go binding | TS binding |
|---|---|---|---|---|
| **Lance** (default) | `LanceVectorStore` | `LanceTextSearch` (BM25-lite over scan) | **Rust FFI**: a thin C-ABI shim crate over the `lancedb` Rust crate, called via cgo (approved approach) | `@lancedb/lancedb` (official TS SDK) |
| **Postgres** | `PostgresVectorStore` (pgvector `<=>`) | `PostgresTextSearch` (native `tsvector`, **`'simple'` config** — no stemming) | `pgx` | `pg` |

Postgres semantics: one table per leaf, name = `{prefix}_{sanitized(P)}`
(lowercase, non-`[a-z0-9_]` → `_`); lazy connect; `SELECT` on a missing table
returns `[]` (parity with an empty Lance leaf); upsert = `INSERT … ON CONFLICT
(eu_id) DO UPDATE`.

### 3.4 Go/Rust FFI scope

The shim crate (`trustrag-lance-ffi`) exposes exactly the three protocol calls
plus `drop`, over a C ABI with JSON-encoded rows. Nothing else crosses the
boundary — retrieval logic, fusion, and grounding stay in Go. The shim is an
implementation detail of `LanceVectorStore` for Go only.

## 4. Deterministic algorithm contract

These MUST produce identical outputs for identical inputs in all languages —
they are covered by shared fixtures (§10).

| Algorithm | Pinned definition |
|---|---|
| Tokenizer | lowercase, matches of `[a-z0-9]+` (ASCII only, no stemming) |
| Stopwords | the fixed 44-word English list in `conformance/stopwords.json` — used ONLY by relevance/faithfulness `content_tokens`, never by BM25 |
| BM25-lite | k1=1.5, b=0.75, idf = ln(1+(N−n+0.5)/(n+0.5)), rows with score 0 dropped, ties broken by input order |
| RRF | contribution `1/(k+rank+1)`, k=60, zero-based rank; fused payload = highest-scoring contributor (first wins ties); order by (−score, eu_id) |
| Dual-query | queries = [original, *reformulations]; every (retriever × query) list feeds ONE fusion; reranker scores the ORIGINAL query only |
| Relevance gate | `content_tokens(evidence_query) ∩ content_tokens(passage) ≠ ∅`; evidence_query = original + reformulations joined by space |
| Faithfulness gate | `tokens(answer) ⊆ tokens(passage)` and answer non-empty (ALL tokens, not content tokens) |
| Refusal | answer is exactly `I can't answer that from the available evidence.`; decision `refused`; empty claims/sources |
| Answer-language chain | reliable detection → explicit override → conversation language → dominant evidence language (stable tie: first seen) → default |
| eu_id formats | block `doc::{order}` · chunked child `doc::{order}::{i}` · vision `doc::img::{image_id}` |
| Chunker | recursive boundaries paragraph(`\n\s*\n`) → line(`\n`) → sentence(`(?<=[.!?])\s+`) → word; defaults max=450 "tokens" (whitespace words), overlap=60; greedy pack, overlap tail = trailing whole pieces within the budget |
| Contextual prefix | indexed `text` = `context + "\n" + chunk`; `citation.passage` = **verbatim chunk, always** |
| Hash fake embedding (tests) | dim 64; per token: `SHA-1(token)` hex as big int `% dim` → +1.0; L2-normalize (zero vector stays zero) |

## 5. Model-client contract

All model IO is injected endpoints; nothing bundled.

- **OpenAI-compatible**: embeddings `POST {base}/embeddings`; chat
  `POST {base}/chat/completions`; rerank `POST {base}/rerank` (Cohere/Jina
  `results[].{index, relevance_score}` shape).
- **Anthropic**: `POST {base}/v1/messages`, headers `x-api-key` +
  `anthropic-version: 2023-06-01`, top-level `system`, required `max_tokens`
  (default 1024), reply = concatenated `content[].text` blocks.
- **Temperature is ALWAYS sent** (default 0.0) on every generation call.
- API keys: referenced by **environment-variable name** in config
  (`api_key_env`); the value is read at call time and travels only in the auth
  header. Never logged, never stored on the client object.
- Every default HTTP transport sends `User-Agent: trustrag` (Cloudflare-fronted
  APIs 403 default library agents).
- Transports are injectable — unit tests are hermetic in all languages.
- The four prompts (grounded-answer system prompt with the verbatim-quote rule,
  vision JSON-description prompt, contextualizer prompt, EN-reformulation
  prompt) are pinned **verbatim** in `conformance/prompts.json`; ports load or
  embed them unchanged.

## 6. Config contract

The §17 config is a language-neutral document (YAML/JSON), key-for-key the
Python schema: `storage` (bucket, partition_hierarchy, endpoint_url) · `llm`
(provider: `openai|anthropic`, model, endpoint, api_key_env, temperature=0,
max_tokens) · `embedding` · `reranker` · `reformulation` · `vision` ·
`vector_store` (backend: `lancedb|postgres`, uri, table_prefix) · `retrieval`
(rrf_k=60, top_k) · `trust` · `multilingual` · `memory` · `signals`.
Unknown keys are an error (strict parsing) in every language.

## 7. Result contract

`Result` serializes to the same JSON in all languages (the conformance suite
compares serialized results): `answer`, `answer_language`, `mode`,
`evidence{decision, supporting_sources, distinct_documents,
retrieval_score_spread, all_claims_verified, languages_in_evidence}`,
`claims[]{claim, supported, sources[]}`, `sources[]{document, passage,
passage_language, page, bbox, source_uri}`, `provenance[]{claim, evidence_unit,
document_id, s3_object, checksum, page, produced_by}`, `missing_evidence[]`.
Citations are **verbatim source text** — never model output, never translated.

## 8. Hooks, telemetry, streaming

- **Hooks** (observe-only, never mutate, a raising hook is swallowed):
  `on_ingest(result)`, `on_retrieve(query, candidates)`, `on_answer(result)`,
  `on_refuse(result)`, `on_chunk(chunk)`. Go: a `Hooks` struct of funcs;
  TS: an object of optional functions.
- **Telemetry**: one event stream. `StageEvent{stage, partition, document_id?,
  duration_ms, tokens{input,output}?, units{images,pages,candidates}?, cost?,
  plugin?, outcome}`. Stage and Outcome enums are the closed Python sets.
  Minimum emission (T1): `fusion` (candidate count) + `generate` (real token
  usage + ok/refused) per `ask()`. Sink = anything with `emit(event)`.
- **Streaming**: chunks are released only AFTER verification. Strict mode:
  sentence-gated (`[^.!?]+[.!?]?` matches, trimmed, empty dropped); normal
  mode: word chunks with trailing space except the last. Never stream raw
  model tokens in strict mode — that would break the guarantee.

## 9. Language-specific implementation notes

### Go
- Module `github.com/muthuishere/trustrag-go`. Layout mirrors capability
  packages (`storage`, `retrieve`, `answer`, `ingest`, …).
- Lance via the Rust FFI shim (§3.4); build with `cargo` → static lib, cgo
  link; prebuilt artifacts per platform in releases (like lancedb's own
  packaging). Everything else is pure Go (pgx, net/http, encoding/json).
- Concurrency: `context.Context` on every IO call; per-retriever fan-out with
  an errgroup is allowed — ORDER of fused output must stay deterministic.
- No reflection-based config: decode into typed structs, reject unknown keys.

### TypeScript
- Package `trustrag` (npm) or `@trustrag/core`. ESM, Node ≥ 20; types shipped.
- `@lancedb/lancedb` for the Lance pair; `pg` for Postgres; `fetch` transport.
- All model/transport seams are injectable functions — same hermetic-test rule.
- The whole public surface is `async`; `stream()` returns an async iterable.

## 10. Conformance suite (the real contract)

A `conformance/` directory in this repo, versioned with the spec:

- `stopwords.json`, `prompts.json` — pinned data (§4, §5).
- `cases/tokenize.json` — text → tokens.
- `cases/bm25.json` — rows+query → ordered (eu_id, score rounded 1e-6).
- `cases/rrf.json` — ranked lists → fused order.
- `cases/faithful.json` — (answer, passage) → supported bool.
- `cases/chunker.json` — text+params → chunks.
- `cases/eu_ids.json` — doc blocks → eu_id list + checksum.
- `cases/language.json` — fallback-chain inputs → answer language.
- `cases/result_roundtrip.json` — Result JSON canonical serialization.
- `cases/e2e_hermetic.json` — corpus + questions → decision/source/passage,
  run with the hash fake embedding + extractive fake LLM (both pinned in §4),
  so every language proves cite-or-abstain end-to-end offline.

**Interop test (CI, opt-in like MinIO):** Python ingests the example corpus
into MinIO → the port under test runs `ask()` against that bucket → answers
must match the hermetic expectations. This is the sentence in §0, executed.

## 11. Versioning

- This spec: `ports-v1`, tracking Python `0.2.x` behavior. A Python change that
  alters any pinned constant/prompt/format bumps `ports-vN` and the fixtures.
- Each port publishes independently but declares `Conformance: ports-v1 (T1)`
  in its README and CI badge.

## 12. Non-goals for ports

- No LangChain/LlamaIndex interop layers. No bundled models. No new backends
  inside a port that Python lacks (propose here first — contract before code).
- No "lenient mode" that skips verification. The guarantee is the product.
