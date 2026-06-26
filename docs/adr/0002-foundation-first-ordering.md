# 0002 — Foundation-first build ordering

Status: accepted · 2026-06-26

## Context

The v6 spec is large (six fused retrieval signals, S3/LanceDB substrate, plugins,
worker, telemetry, judge). Two viable orderings: a thin **walking skeleton**
end-to-end first, or **foundation-first** (build each horizontal layer before
composing). The owner chose foundation-first.

## Decision

Build in layers L0→L6, each as one or more OpenSpec changes, test-first:

- **L0** scaffold · **L1** core domain (types, config/signals, plugins, provenance)
  · **L2** storage/worker/telemetry/access · **L3** ingest/extractors/vision/
  structure/language · **L4** embedding/vector/retrievers/fusion · **L5** answer/
  verify/eval (the guarantee) — ship `0.1.0` · **L6** graph/wiki/streaming/memory/
  MCP/judge-online/auth-enforcement/agentic.

## Consequences

- **Risk:** foundation-first can build generality (worker, telemetry, access)
  before a single answer flows end-to-end.
- **Mitigation:** a minimal `smoke-e2e` change lands the moment storage+ingest
  exist (within L2/L3), wiring ingest→vector→ask over deterministic fakes, and is
  kept green by every later layer so the layers can't silently drift apart.
- Tests use deterministic fakes (hash-based embeddings, evidence-echoing LLM); the
  `example/` integration path uses local Ollama (`Taskfile.local.yml`).
