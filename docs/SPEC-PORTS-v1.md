# CiteNexus Language-Port Specification v1 — Go & TypeScript

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
| Construct | `CiteNexus(base_uri, embedder=…, generator=…)` | `citenexus.New(baseURI, citenexus.WithEmbedder(…), …)` | `new CiteNexus(baseUri, { embedder, generator })` |
| From config | `CiteNexus.from_config(cfg)` | `citenexus.FromConfig(cfg)` | `CiteNexus.fromConfig(cfg)` |
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

### 3.4 The Rust core (`citenexus-core`) — Go's engine room

Since Go must link Rust for Lance anyway, the bridge is a single Rust crate
carrying everything Rust does better than the Go ecosystem, over one C ABI
with JSON in/out:

1. **store** — the Lance `VectorStore` calls: `upsert / search / scan / drop`.
2. **extract** — `extract(bytes, source_type) -> ExtractedDoc JSON` (blocks +
   images + structure) for pdf (`pdfium-render`), docx/pptx (OOXML-direct via
   `quick-xml` + zip), html (`scraper`/html5ever), md (`pulldown-cmark`). The
   structural source types — `code` (symbol EUs), and the schema **artifact**
   extractors `schema_sql` (SQL DDL → one verbatim EU per table) and
   `schema_openapi` (OpenAPI/JSON-Schema → one verbatim EU per endpoint/component,
   both reusing `table_schema`) — are deterministic byte-parity twins of their
   Python references. They emit **EUs only, no edges** (`ExtractedDoc` has no edge
   channel); structural edges (code `calls`, schema FK/`$ref`) come from an
   *injected* distiller through the `graph_distiller=` seam, never the core
   extractor. Live-database connectors and sampled shapes are **out of core** — a
   schema is ingested only as an artifact (a `.sql` dump, an `openapi.json`).
3. **detect** — fastText **lid.176 via the pure-Rust `fasttext` crate** —
   the exact spec model, so detection is byte-identical with Python.
4. **rrf** — `citenexus_rrf(lists_json, k) -> fused eu_id order`. Reciprocal-rank
   fusion is *pure* rank arithmetic (no tokenization, no Unicode, no key), so
   ADR-0006 moves it into the core: every SDK's fusion is a thin binding, and the
   old per-language `rrf` helpers are **deprecated, not removed** (kept as the
   native-toolchain-free path, pinned by `cases/rrf.json`).

The boundary is cut by **what the code is** (ADR-0006): only pure, text-free
computation moves in. The cite-or-abstain **gate**, **BM25**, **chunker**, and
the **tokenizer** stay per host language — they must stay hackable without a Rust
toolchain, and relocating their Unicode-sensitive case-folding would silently
diverge on exactly the non-Latin languages CiteNexus targets. Their drift is
killed instead by the shared conformance-vector suite (§10), which now carries a
**multilingual/Unicode-edge corpus** (`cases/multilingual.json`: Turkish
dotless-ı, German ß, NFC vs NFD, CJK, combining marks) that every port runs. One
bridge to maintain instead of five parser dependencies, and extraction/fusion
output is identical across Python and Go by construction. TS MAY adopt the same
crate via napi-rs in a later rev; ports-v1 allows TS to use its native libs
(conformance fixtures are the arbiter either way).

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
- **Typed endpoint objects, app-resolved keys**: connections are declared as
  typed endpoints (OpenAI-style, Gemini, Anthropic, OpenRouter, Ollama, custom
  auth shapes) carrying base_url + key + headers + timeout + pre/post hooks.
  THE LIBRARY READS NO ENVIRONMENT — the application passes the key value,
  held in a redaction-safe wrapper (Python SecretStr; Go/TS equivalents must
  redact in String()/toString()/JSON). The endpoint type selects the wire
  protocol. Wire clients receive only base_url + model + transport.
- Every default HTTP transport sends `User-Agent: citenexus` (Cloudflare-fronted
  APIs 403 default library agents).
- Transports are injectable — unit tests are hermetic in all languages.
- The five prompts (grounded-answer system prompt with the verbatim-quote
  rule, vision JSON-description prompt, contextualizer prompt, EN-reformulation
  prompt, wiki-distillation prompt) are pinned **verbatim** in
  `conformance/prompts.json`; ports load or embed them unchanged.
- **Every model-backed capability ports the same way** — generator (OpenAI +
  Anthropic), reformulator, contextualizer, vision, and the wiki distiller are
  all plain HTTP + pinned prompt + JSON parse; none needs a language-specific
  SDK. Likewise Postgres is pinned SQL (§3.3), and the LLM wiki's artifacts
  (`pages.json` + Markdown tree) are language-neutral S3 objects — a wiki
  built by any implementation is navigable by every other (read-side is T1-
  adjacent even though distillation itself is T2).

## 6. Config contract

The §17 config is a language-neutral document (YAML/JSON), key-for-key the
Python schema: `storage` (bucket, partition_hierarchy, endpoint_url) · `llm`
(model, endpoint: typed-endpoint object, temperature=0, max_tokens) · `embedding` · `reranker` · `reformulation` · `vision` ·
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

### The shared Rust core — target architecture (DECIDED)

**One Rust library, FFI for all.** `citenexus-core` is the single engine for
every language — the pydantic-v2 / tokenizers / lancedb playbook:

```
                     citenexus-core (Rust)
   v1: store (lance) · extract (pdf/docx/pptx/html/md) · detect (lid.176)
   v2: + rrf (pure rank arithmetic — no tokenizer, no Unicode: safe to move,
        ADR-0006). The gate · BM25 · chunker · tokenizer STAY per host language
        (Unicode-sensitive + must stay hackable without a Rust toolchain); their
        drift is killed by the shared conformance vectors — incl. the
        multilingual/Unicode corpus — NOT by relocation
             /                |                  \
        cgo C-ABI          napi-rs              pyo3
           Go             TypeScript            Python
      (required from     (native libs OK in   (adopts the core when the
       day one)           ports-v1; SHOULD      pyo3 binding lands —
                          migrate to core)      strangler-style, features
                                                never stall on the rewrite;
                                                Python stays the BEHAVIOR
                                                reference throughout)
```

**The core is the engine, not the brain.** Orchestration NEVER moves in:
the ask flow, cite-or-abstain, plugin seams, hooks, config, and all model
HTTP calls stay in each host language (IO-bound — no Rust win, and the
guarantee logic must stay hackable without a Rust toolchain). Boundary rule:
JSON (Arrow allowed for row batches) in/out, **no callbacks across FFI**.
Wherever the core has a capability, a binding uses it; native libraries
remain only where the core lacks coverage or a platform cannot link it.

### Go
- Module `github.com/muthuishere/citenexus-go`. Layout mirrors capability
  packages (`storage`, `retrieve`, `answer`, `ingest`, …).
- Lance + extraction + detection via `citenexus-core` (cgo); prebuilt static
  libs per platform in releases. Everything else pure Go (pgx, net/http).
- Concurrency: `context.Context` on every IO call; per-retriever fan-out with
  an errgroup is allowed — ORDER of fused output must stay deterministic.
- No reflection-based config: decode into typed structs, reject unknown keys.

### TypeScript
- Package `citenexus` (npm) or `@citenexus/core`. ESM, Node ≥ 20; types shipped.
- `@lancedb/lancedb` for the Lance pair; `pg` for Postgres; `fetch` transport.
- Extraction: native libs allowed in ports-v1 (pdfjs-dist, OOXML-direct); the
  napi binding of `citenexus-core` is the parity path and SHOULD replace them
  once published.
- All model/transport seams are injectable functions — same hermetic-test rule.
- The whole public surface is `async`; `stream()` returns an async iterable.

## 10. Conformance suite (the real contract)

A `conformance/` directory in this repo, versioned with the spec:

- `stopwords.json`, `prompts.json` — pinned data (§4, §5).
- `cases/tokenize.json` — text → tokens.
- `cases/bm25.json` — rows+query → ordered (eu_id, score rounded 1e-6).
- `cases/rrf.json` — ranked lists → fused order (also the byte-parity oracle for
  the core `citenexus_rrf`, ADR-0006).
- `cases/faithful.json` — (answer, passage) → supported bool.
- `cases/chunker.json` — text+params → chunks.
- `cases/multilingual.json` — the ADR-0006 anti-drift corpus: `tokenize` / `bm25`
  / `chunker` / `gate` vectors over a Unicode-edge corpus (Turkish dotless-ı,
  German ß, NFC vs NFD, CJK, combining marks). Pins the per-host gate/BM25/chunker
  — which STAY per language — against the tokenizer divergence that an ASCII-only
  suite would miss. Every port (Python/Go/JS) runs it.
- `cases/eu_ids.json` — doc blocks → eu_id list + checksum.
- `cases/language.json` — fallback-chain inputs → answer language.
- `cases/result_roundtrip.json` — Result JSON canonical serialization.
- `cases/e2e_hermetic.json` — corpus + questions → decision/source/passage,
  run with the hash fake embedding + extractive fake LLM (both pinned in §4),
  so every language proves cite-or-abstain end-to-end offline.
- `cases/vision_orchestration.json` — the two-phase vision seam (ADR-0005, §9):
  the ordered `emit` list of `PendingVisionRequest`s (byte-identical data-URI +
  prompt + `source_ref`), the `fulfilled` records, the `assembled` figure EUs,
  and a `degrade` join where an unfulfilled request yields no EU. The two `images`
  carry PNG vs JPEG magic bytes: the emitted `payload.image_url` declares each
  image's **true** media type (sniffed from the magic bytes — png/jpeg/gif/webp,
  else png), so a port MUST sniff the format, not hardcode `image/png`.

**The vision FFI seam.** Vision is host-fulfilled: the core exposes two bound
entry points across the FFI — **emit** (parse an artifact → the `emit` list) and
**assemble** (`{request_id: description}` → figure EUs). Between them each port
implements a thin, in-language **fulfiller**: "POST this payload → return the
description string." The API key lives only in that fulfiller's transport and
never crosses into the core. Ports reproduce `emit` and `assembled` from the
fixture byte-for-byte; only the raw model call in the middle differs per
language. Degrade-to-text is part of the contract: a request the host leaves
unfulfilled (or fails) yields no figure EU and never fails ingest.

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
