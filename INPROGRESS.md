# In Progress — resume pointer

Working state for picking the build back up. The durable plan + conventions live
in [`CLAUDE.md`](CLAUDE.md); the living spec is under `openspec/specs/`; this file
is just "where we are right now."

_Last updated: 2026-06-26 · branch `main` (latest)._

## Snapshot

| Layer | Status |
|---|---|
| **L0** scaffold (uv/Taskfile/CI/MinIO) | ✅ done, on main |
| **L1** domain (core-types, config/signals, plugins, provenance) | ✅ done, on main |
| **L2** substrate (storage/MinIO, worker, telemetry, access, smoke-e2e) | ✅ done, on main |
| **L3** ingest (extractors, language-detect, evidence+structure, vision, ingest-pipeline) | ✅ done, on main |
| **L4** retrieval (embedding-openai, vector/lexical/structure retrievers, RRF fusion, rerank, engine) | ✅ done, on main |
| **L5** answer / verify / eval (+ judge) → ship 0.1.0 | ⏳ **next** |
| **L6** graph · wiki · streaming · memory · MCP · auth-enforcement | ⏳ not started |

**Living spec:** 17 capabilities archived in `openspec/specs/`. No active OpenSpec changes.

## Next steps (in order)

1. **L5 answer/verify/eval** — grounded generation over an injected LLM
   (OpenAI-compatible / Ollama), always-on faithfulness gate, cite-or-abstain,
   answer-language invariant, `evaluate(csv)` + groundedness/citation metrics,
   offline judge. Wire `RetrievalEngine` (L4) into a public `retrieve()` and a real
   `ask()` (replacing the smoke pipeline's fake-only path). **Ship `0.1.0` to PyPI.**
2. **L6** — graph (Leiden) · wiki (distill/index/lint) · streaming · conversation
   memory · MCP server · external-store auth enforcement.

### What L4 gives the next session
- `trustrag.retrieve.RetrievalEngine` — run retrievers → RRF (k=60) → rerank top-N.
- `VectorRetriever` (dense, over `LeafVectorStore`), `LexicalRetriever` (BM25-lite
  over `scan()`), `StructureRetriever` (structure-index walk). `rrf_fuse`.
- `OpenAICompatibleEmbedding` (dense, `/v1/embeddings`) + `OpenAICompatibleReranker`
  — injected transport; real endpoints are integration-only.
- L5 should compose these into `retrieve()`/`ask()` and add the LLM generation step.

## Resume / verify

```bash
task setup                       # uv sync
task check                       # ruff + mypy --strict + unit tests (the gate)
task local:minio:up              # start MinIO (S3) — needed for integration tests
uv run pytest -m integration -q  # MinIO + fastText integration suite
```

- **Tests (last full run):** 302 unit + 4 integration green (1 skipped: embed endpoint, Ollama down).
- **MinIO**: `compose.yaml`, S3 `:19000` / console `:19001` (`minioadmin`), bucket `trustrag-local`.
- **Ollama**: currently **down** — real embedding/LLM/rerank integration tests skip until it's up (`task local:ollama:up`). All unit tests use deterministic fakes.
- **fastText `lid.176`** caches under `assets/models/` (gitignored), downloaded on first real detect.

## Open decisions

- **PyPI dist-name** — `trustrag` is taken; pick a suffix before the first publish (import stays `trustrag`).
- **BGE-M3 sparse** — dense embedding works over Ollama; true BGE-M3 sparse needs a sparse-capable endpoint (FlagEmbedding/infinity). Lexical signal currently uses BM25-lite over stored text.
