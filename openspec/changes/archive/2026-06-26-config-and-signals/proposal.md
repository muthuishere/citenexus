## Why

TrustRAG's public surface is convention-over-configuration (§15): `TrustRAG("s3://bucket")`
must just work, while the single most important knob — which of the six retrieval signals a
client builds and queries — has to be declared once and then honored everywhere. Without a
typed config layer and a signal-capability gate, ingest would pay for graph/wiki layers a
client never uses, and there would be no place to validate that a deployment stays within
its intended capabilities. This is L1 foundation: every later layer (ingest, retrieval,
answer) consults config and the signal gate.

## What Changes

- New typed configuration schema covering the full §17 surface (storage incl.
  `partition_hierarchy`, llm, embedding, reranker, vision incl. prefilter, vector_store,
  graph, retrieval, trust, multilingual, access_control, plugins, provenance, worker,
  telemetry, memory, judge, streaming) with sane defaults (strict mode, `rrf_k=60`,
  `top_k=11`, `lexical_signal=bge_m3_sparse`, `detect_confidence_threshold=0.50`,
  `answer_in_query_language=true`).
- A config loader that accepts a dict, a YAML file, or environment overrides with a defined
  precedence, plus a `from_config(...)` entry point.
- A `Signal` enum `{embedding, text, graph, community, structure, wiki}` and gating
  predicates that answer "does ingest build signal X?" and "does ask query signal X?".
  Declaring `signals=["embedding","text"]` gates OUT graph/community/wiki for both phases.
- An optional warn-only validation pass against `trustrag.validate.yaml`
  (`allowed_signals`, `allowed_doc_types`): divergence emits a WARNING and proceeds; it
  NEVER raises, and a missing file means no check.
- No pipeline behavior — this change delivers typed config + signal gating + validation only.

## Capabilities

### New Capabilities

- `config-and-signals`: typed configuration schema + loader, the signal-capability gate that
  ingest/ask consult, and the optional warn-only validation contract.

### Modified Capabilities

(none — greenfield)

## Impact

- New modules: `src/trustrag/config/schema.py`, `config/loader.py`, `config/signals.py`,
  `config/validate.py`.
- Consumed later by the ingest pipeline (signal-gated build) and the retrieval/answer layer
  (signal-gated query). No external dependencies beyond pydantic v2 (+ stdlib yaml via a
  small parser or PyYAML if added). mypy --strict, `task check` gate.
