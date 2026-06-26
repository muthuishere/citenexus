# In Progress — resume pointer

Working state for picking the build back up. The durable plan + conventions live
in [`CLAUDE.md`](CLAUDE.md); the living spec is under `openspec/specs/`; this file
is just "where we are right now."

_Last updated: 2026-06-26 · branch `main` · last green commit `7f86858`._

## Snapshot

| Layer | Status |
|---|---|
| **L0** scaffold (uv/Taskfile/CI/MinIO) | ✅ done, on main |
| **L1** domain (core-types, config/signals, plugins, provenance) | ✅ done, on main |
| **L2** substrate (storage/MinIO, worker, telemetry, access, smoke-e2e) | ✅ done, on main |
| **L3** ingest (extractors, language-detect, evidence+structure, vision, ingest-pipeline) | ✅ done, on main |
| **L4** retrieval | 🔶 **partial** — embedding client + `Candidate` seam + `scan()` on main; **retrieve-engine in progress** |
| **L5** answer / verify / eval (+ judge) → ship 0.1.0 | ⏳ not started |
| **L6** graph · wiki · streaming · memory · MCP · auth-enforcement | ⏳ not started |

**Living spec:** 16 capabilities archived in `openspec/specs/` (L1–L3 + embedding-openai).

## In progress — `retrieve-engine` (L4)

The `retrieve-engine` OpenSpec change is being implemented:
`src/trustrag/retrieve/{vector,lexical,structure,fusion,rerank,engine}.py` +
`tests/retrieve/`. These files may be **uncommitted in the working tree** (kept off
`main` until green so `main` always builds). The shared `Candidate`/`RetrievalSignal`
types (`retrieve/types.py`) and `LeafVectorStore.scan()` are already committed.

**To finish L4:** run the full gate; if green, `openspec archive embedding-openai retrieve-engine`, then commit + push. Then wire `RetrievalEngine` into a public `retrieve()` (and later `ask()` at L5).

## Next steps (in order)

1. **Land retrieve-engine** (above) → L4 done.
2. **L5 answer/verify/eval**: grounded generation over an injected LLM (OpenAI-compatible / Ollama), always-on faithfulness gate, cite-or-abstain, answer-language invariant, `evaluate(csv)` + groundedness/citation metrics, offline judge. Upgrade `SmokePipeline.ask` → real `ask()` using `RetrievalEngine`. **Ship `0.1.0` to PyPI.**
3. **L6**: graph (Leiden) · wiki (distill/index/lint) · streaming · conversation memory · MCP server · external-store auth enforcement.

## Resume / verify

```bash
task setup                       # uv sync
task check                       # ruff + mypy --strict + unit tests (the gate)
task local:minio:up              # start MinIO (S3) — needed for integration tests
uv run pytest -m integration -q  # MinIO + fastText integration suite
```

- **Tests (last full run):** 269 unit + 4 integration green (before retrieve-engine).
- **MinIO**: `compose.yaml`, S3 `:19000` / console `:19001` (`minioadmin`), bucket `trustrag-local`.
- **Ollama**: currently **down** — real embedding/LLM integration tests skip until it's up (`task local:ollama:up` to pull models). All unit tests use deterministic fakes.
- **fastText `lid.176`** model caches under `assets/models/` (gitignored), downloaded on first real detect.

## Open decisions

- **PyPI dist-name** — `trustrag` is taken; pick a suffix before the first publish (import stays `trustrag`).
- **BGE-M3 sparse** — dense embedding works over Ollama; true BGE-M3 sparse needs a sparse-capable endpoint (FlagEmbedding/infinity). Lexical signal currently uses BM25-lite over stored text.
