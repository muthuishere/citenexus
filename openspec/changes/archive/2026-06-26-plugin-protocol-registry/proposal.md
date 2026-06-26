## Why

Nothing in the TrustRAG pipeline may be hardwired (v6 §4b): every stage —
extraction, chunking, embedding, vision, graph extraction, retrieval, reranking,
judging, evaluation, language detection, memory — must be a swappable, typed
extension point so the framework can evolve (new models, new extractors, custom
retrievers) without touching the core, and so the artifact-versioning system
(§4c) can record exactly what produced each artifact. This change establishes
that seam before any concrete stage is built.

## What Changes

- Add a common `Plugin` base carrying a required `plugin_version`, and the
  **11 typed plugin protocols** (ABCs) from §4b/§11a/§16b/§18: `ExtractorPlugin`,
  `ChunkerPlugin`, `EmbeddingPlugin`, `VisionPlugin`, `GraphExtractorPlugin`,
  `RetrieverPlugin`, `RerankerPlugin`, `JudgePlugin`, `EvaluatorPlugin`,
  `LanguageDetectorPlugin`, `MemoryPlugin` — each declaring its input/output
  contract via abstract method signatures.
- Add a `PluginRegistry` with `register_plugin`, `register_retriever` (retrievers
  form a fusion *set*, not a single slot), a `use(plugin)` verb (§15) that
  dispatches by protocol type, and `resolve(protocol)` lookup.
- Enforce **typed, not duck-typed** registration: an object that does not satisfy
  the declared protocol is REJECTED at registration time (raises).
- Establish that **built-ins are plugins too** — no privileged code path; the
  default BGE-M3 embedder, the six retrievers, etc. register through the same
  mechanism they would extend.
- Establish that **fusion stays in core**: a `RetrieverPlugin` only contributes a
  ranked candidate list; it cannot perform RRF/grounding and therefore cannot
  bypass the evidence guarantees.
- No concrete implementations land here — only the protocol layer + registry.

## Capabilities

### New Capabilities
- `plugin-protocol-registry`: the typed plugin protocol ABCs, the common
  versioned `Plugin` base, and the registry (register/resolve/use + retriever
  fusion set) with enforced type-conformant registration.

### Modified Capabilities
<!-- none — this is foundational -->

## Impact

- New module `src/trustrag/plugins/` (`base.py`, `registry.py`).
- Downstream contract: `provenance-and-rebuild` consumes each plugin's
  `plugin_version` for the `produced_by` stamp (§4c); every later stage change
  (ingest, embedding, retrieval, …) implements one of these protocols rather than
  adding a bespoke interface.
- Public API: `rag.use(plugin)` (§15) is the single registration verb surfaced to
  callers.
- No external dependencies; standard-library `abc` only.
