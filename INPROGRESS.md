# In Progress — resume pointer

Working state for picking the build back up. The durable plan + conventions live
in [`CLAUDE.md`](CLAUDE.md); the living spec is under `openspec/specs/`; this file
is just "where we are right now."

_Last updated: 2026-06-30 · branch `main`._

## Snapshot

| Layer | Status |
|---|---|
| **L0** scaffold (uv/Taskfile/CI/MinIO) | ✅ done, on main |
| **L1** domain (core-types, config/signals, plugins, provenance) | ✅ done, on main |
| **L2** substrate (storage/MinIO, worker, telemetry, access, smoke-e2e) | ✅ done, on main |
| **L3** ingest (extractors, language-detect, evidence+structure, vision, ingest-pipeline) | ✅ done, on main |
| **L4** retrieval (embedding-openai, vector/lexical/structure retrievers, RRF fusion, rerank, engine) | ✅ done, on main |
| **L5** answer / verify / eval → 0.1.0-ready | ✅ done, local |
| **L6a** graph · wiki · streaming · memory | ✅ done, local |
| **L6b** MCP · external auth enforcement · richer graph/wiki | ⏳ **next** |

**Living spec:** 22 capabilities archived in `openspec/specs/`. No active OpenSpec changes.

## Next steps (in order)

1. **Release** — choose the PyPI dist-name (`trustrag` is taken; import remains
   `trustrag`), build, and publish with trusted publishing. Current local version
   is `0.2.0` because graph/wiki/streaming/memory are included.
2. **L6b** — MCP server · external-store auth enforcement · richer graph entity
   extraction/community clustering · richer wiki distillation/lint.

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
