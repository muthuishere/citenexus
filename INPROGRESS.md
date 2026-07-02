# In Progress — resume pointer

Working state for picking the build back up. The durable plan + conventions live
in [`CLAUDE.md`](CLAUDE.md); the living spec is under `openspec/specs/`; this file
is just "where we are right now."

_Last updated: 2026-07-02 · branch `main`._

## Snapshot

| Layer | Status |
|---|---|
| **L0** scaffold (uv/Taskfile/CI/MinIO) | ✅ done, on main |
| **L1** domain (core-types, config/signals, plugins, provenance) | ✅ done, on main |
| **L2** substrate (storage/MinIO, worker, telemetry, access, smoke-e2e) | ✅ done, on main |
| **L3** ingest (extractors, language-detect, evidence+structure, vision, ingest-pipeline) | ✅ done, on main |
| **L4** retrieval (embedding-openai, vector/lexical/structure retrievers, RRF fusion, rerank, engine) | ✅ done, on main |
| **L5** answer / verify / eval → 0.1.0-ready | ✅ done, on main |
| **L6a** graph · wiki · streaming · memory | ✅ done, on main |
| **L5+** real answering-LLM client · `from_config` · runnable example · hosted stack | ✅ done, local |
| **L6b** MCP · external auth enforcement · richer graph/wiki | ⏳ **next** |

**Living spec:** 22 capabilities archived in `openspec/specs/`. No active OpenSpec changes.

## Next steps (in order)

1. **Release** — choose the PyPI dist-name (`trustrag` is taken; import remains
   `trustrag`), build, and publish with trusted publishing. Current local version
   is `0.2.0` because graph/wiki/streaming/memory are included.
2. **L6b** — MCP server · external-store auth enforcement · richer graph entity
   extraction/community clustering · richer wiki distillation/lint.

## Session 2026-07-02 — real endpoints + runnable example (local, uncommitted)

Closed the last L5 gap (a real answering-LLM client) and made the library
provably work end-to-end over cheap hosted endpoints:

- **`OpenAICompatibleGenerator`** (`answer/generator.py`) — the real chat client
  behind `ask()`. Always sends `temperature` (default 0.0) → "temp-0 grounded"
  is now enforced, not just a config default. Mirrors the embed/rerank seam
  (injected `transport`, stdlib urllib default, key only via `api_key_env`).
- **`TrustRAG.from_config(...)`** (`client.py`) — one call builds embedding +
  generator + reranker plugins from a typed `TrustRAGConfig`; transports are
  injectable so it's unit-tested hermetically.
- **Config**: added `api_key_env` to `EmbeddingConfig` + `RerankerConfig` (keyed
  hosted embed/rerank endpoints like Jina need it).
- **User-Agent fix**: all three default urllib transports now send
  `User-Agent: trustrag` — Jina (behind Cloudflare) 403s the default urllib UA.
- **`example/`** — multilingual corpus (en/de/fr) + `golden.csv` + `run.py`.
  `task local:example` runs ingest → ask → evaluate. Verified live: German Q
  answered in German, groundedness + citation 100%, correct abstention on the
  rest (extractive verifier is conservative — Gemini rephrases, gate abstains).
- **Cheap hosted stack** (default): Jina embed+rerank, Gemini `gemini-2.5-flash`
  LLM, LocalFs storage. No GPU, no containers.
- **compose.yaml** — added opt-in `infinity` service (`models` profile) for
  all-local bge-m3 embed + bge-reranker-v2-m3 on one port. (Downloaded fine but
  its reranker weights stalled on a HF hang twice — hence hosted is the default.)
- **Secrets**: vsync vault `infra/vault/dev/.env.dev` (env `dev`, profile
  `stock-core-vault`), pushed encrypted to S3. `.vsync` pin added (commit it).
  Tests: 323 unit green; live integration 4 passed (Jina embed + generator smoke).

**Committed** on branch `feat/real-endpoints-and-example` (2 commits: real
endpoints/example, then telemetry). Not pushed. `git add .vsync` done.

### Telemetry / observability (committed)
- `OpenAICompatibleGenerator.last_usage` — parses the OpenAI `usage` block into
  `TokenUsage` (input/output tokens) after each call.
- `TrustRAG(sink=...)` / `from_config(sink=...)` — `ask()` emits a `generate`
  `StageEvent` with real token usage + answer/refuse `Outcome`, partition-attributed.
  No sink = silent no-op. The cost view + quality counters already read this stream.

### Multi-provider LLM + vision-into-evidence (committed this session)
- **3 LLM providers**: `LLMConfig.provider` (openai | anthropic). OpenAI-compat
  covers OpenAI + Gemini(OpenAI endpoint) + Ollama + OpenRouter; `AnthropicGenerator`
  is the native Messages API. `from_config` picks the client.
- **Vision client**: `OpenAICompatibleVision` (VL endpoint, base64 image → data URI,
  JSON description, prose fallback). Built from `VisionConfig` when enabled.
- **Vision-into-evidence**: `build_vision_units` + `IngestPipeline(vision=...)`.
  Doc images (any type) → prefilter → describe → figure EU (text=description,
  cite=image page/bbox, eu_id `{doc}::img::{id}`). GUARDED: no client / no bytes /
  per-image error → text-level only, never fails. `TrustRAG(vision=...)` +
  `from_config(vision_transport=...)`.
- ⚠️ **ONE STEP LEFT for real PDFs**: the built-in extractors don't PERSIST image
  bytes yet (`ImageRef.blob_key` is None). So real PDFs feed no bytes to the VL
  model until pdf/docx/pptx extractors capture+persist the raster to a blob_key.
  Wiring + degradation are proven with FakeVision + a persisted blob.

### Contextual chunking + web crawl (committed this session)
- **Recursive chunker** (`evidence/chunker.py`): boundary-aware (para→line→
  sentence→word), ~450 tok / ~60 overlap, no tokenizer dep.
- **Contextual retrieval** (`evidence/contextualize.py`): a SMALL injected model
  writes a 50-100 tok situating prefix per chunk (Anthropic technique; ~35/49/67%
  failure cuts). Enhancement-only — any failure degrades to the bare chunk.
- **Parent-child builder** (`evidence/chunked_builder.py`): oversized blocks →
  child EUs (`{doc}::{order}::{i}`). Context prefix goes in indexed `text`; the
  citation `passage` stays VERBATIM (safety invariant for legal/medical).
- **Web crawl** (`ingest/web.py`): `rag.ingest("https://…")` fetches+indexes;
  `rag.crawl(seed)` BFS same-domain (page/depth capped). No new dep.

⚠️ **NOT yet the default**: `build_chunked_units` is opt-in; `build_evidence_units`
(one-EU-per-block) is still what ingest uses. Switching the default changes
eu_id/provenance for ALL docs — deliberate change, do with user. Also needs a
`context_model` config section (small model) + `from_config` wiring so the
contextualizer is built from config.

### EN dual-query RRF + core fixes (committed this session — LIVE-VERIFIED)
- **QueryReformulator** (`retrieve/reformulate.py`): small model rewrites the
  query in English (temp 0, keeps names/numbers verbatim); **shared cache** per
  query (failures cached too). `ReformulationConfig` in schema; built by
  `from_config`. Enhancement-only → None degrades to single-query.
- **RetrievalEngine.retrieve(extra_queries=…)**: RAG-Fusion — every
  (retriever x query) list feeds one RRF (k=60); reranker sees the ORIGINAL query.
- **Relevance gate**: the EN reformulation also counts for relevance overlap
  (same question in evidence's language). Citations + faithfulness unchanged.
- **fastText lid.176 by default in from_config** (§11a): heuristic mislabelled
  fr→es at ingest and poisoned the answer language. Tests inject HeuristicDetector.
- **Verbatim-quote system prompt**: real LLMs rephrased → extractive gate
  refused; the prompt now demands word-for-word quoting (gate unchanged).
- **Example live result** (Jina + Gemini): **2/5 → 4/5 answered**, correct
  languages (en/de/fr), 100% grounded+cited, remaining refusal is the correct
  out-of-corpus one. Expected support 40% → 80%.

### Open threads (asked for by user, NOT yet built — sequence for next session)
Priority order by "retrieval must be right for legal/medical":
1. **Chunker / splitting (HIGHEST leverage)** — today `build_evidence_units` is
   *one EU per block*, and the PDF extractor emits *one block per page*. So a legal
   citation points at a whole page, not a clause, and the faithfulness gate over-
   abstains. Need a real sentence/token-window chunker with overlap. ⚠️ Changes
   `eu_id`/provenance semantics — do with the user present, not unsupervised.
2. **Karpathy LLM-wiki (§10b)** — replace the deterministic wiki stand-in with an
   injected `WikiDistiller` plugin (LLM), cross-referenced concept + entity pages
   as a browsable **Markdown tree in S3** + `pages.json` manifest, a `lint` pass.
   Reuse graph entity resolution. Navigate-not-cite invariant already enforced —
   this is why the wiki can't hurt correctness (it only adds recall; every hit
   resolves down to bbox-cited EUs; the faithfulness gate still runs).
3. **Emit telemetry from ingest + retrieve + rerank + embedding** — only the
   `generate` stage emits so far; extend to the other stages for full cost/latency.
4. **Extractor image-byte capture** — make pdf/docx/pptx/html extractors persist
   the actual image raster to a `blob_key` so the (now-wired) vision path feeds
   real bytes to the VL model. This is the last step for real-PDF vision.
5. **Audio** — dropped for now per user (was: Whisper-style transcribe plugin).

Design decisions locked with user: wiki depth = full (concept+entity pages, cross-
refs, index); storage = browsable Markdown tree + JSON manifest; **tool surface =
the library API itself** (no CLI/MCP — users import, give URLs, call ingest/ask;
everything config-driven + plugin-swappable, toolnexus "right-sized" style).

### What L5 gives the next session
- `trustrag.retrieve.RetrievalEngine` — run retrievers → RRF (k=60) → rerank top-N.
- `VectorRetriever` (dense, over `LeafVectorStore`), `LexicalRetriever` (BM25-lite
  over `scan()`), `StructureRetriever` (structure-index walk). `rrf_fuse`.
- `OpenAICompatibleEmbedding` (dense, `/v1/embeddings`) + `OpenAICompatibleReranker`
  — injected transport; real endpoints are integration-only.
- `TrustRAG` public client now exposes `ingest()`, `retrieve()`, `ask()`, and
  `stream()`, memory `recall()`, and `evaluate(csv)`.
- `AnswerFlow` verifies cite-or-abstain with a conservative token faithfulness gate.
- `EvaluationReport` gives deterministic aggregate metrics from golden CSVs.
- Graph and wiki are deterministic rebuildable JSON artifacts and retrievers that
  resolve down to EU candidates before answer generation.
- Memory is partition-scoped conversation context used to enrich retrieval queries;
  it is not treated as citation evidence.
- Streaming emits chunks from an already verified `Result`; strict mode is
  sentence-gated.

## Resume / verify

```bash
task setup                       # uv sync
task check                       # ruff + mypy --strict + unit tests (the gate)
task local:minio:up              # start MinIO (S3) — needed for integration tests
uv run pytest -m integration -q  # MinIO + fastText integration suite
```

- **Tests (last full run):** 311 unit green; 5 integration deselected.
- **MinIO**: `compose.yaml`, S3 `:19000` / console `:19001` (`minioadmin`), bucket `trustrag-local`.
- **Ollama**: currently **down** — real embedding/LLM/rerank integration tests skip until it's up (`task local:ollama:up`). All unit tests use deterministic fakes.
- **fastText `lid.176`** caches under `assets/models/` (gitignored), downloaded on first real detect.

## Open decisions

- **PyPI dist-name** — `trustrag` is taken; pick a suffix before the first publish (import stays `trustrag`).
- **BGE-M3 sparse** — dense embedding works over Ollama; true BGE-M3 sparse needs a sparse-capable endpoint (FlagEmbedding/infinity). Lexical signal currently uses BM25-lite over stored text.
