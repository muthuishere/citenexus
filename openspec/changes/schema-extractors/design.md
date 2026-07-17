## Context

`structural-code-graph` establishes the pattern: a deterministic extractor in the
Rust core emits verbatim symbol EUs (no edges); edges come from an **injected
distiller** through the `graph_distiller=` seam; a typed intake verb enforces the
`graph` signal. Schemas reuse all of it. Two hard facts from the 2026-07-17 review
shape this design:

1. `citenexus_extract` returns an `ExtractedDoc` with **no edge channel** (only
   blocks + images — `rust/src/types.rs`, `extract/types.py`). So the schema
   extractor **cannot** emit edges; edges must come from an injected distiller, like
   code.
2. Live-DB connectors are a network-service surface (scope-gate OUT), and sampled
   schemaless shapes (Mongo/Redis) are synthesized (no verbatim span → fail
   cite-or-abstain; sampling reads data → not "schema-only"). Both are cut from
   core here.

## Goals / Non-Goals

**Goals:**
- Core extractors for SQL DDL + OpenAPI/JSON-Schema **artifacts** → one verbatim,
  citable EU per schema object, reusing `table_schema`.
- FK/`$ref`/type-reference edges via an **injected schema distiller**, marked
  `confidence=extracted`.
- `rag.schema.ingest_from(file|doc)` — graph-required, Python-wired.

**Non-Goals:**
- Emitting edges from the core extractor (the ABI can't; edges are injected).
- Live-DB connectors and sampled shapes (separate connector change/consumer repo).
- Row data of any kind.
- A new structure type (reuse `table_schema`).
- The Go/JS graph seam (unwired; later change).

## Decisions

### 1. Extractor emits EUs only; edges come from an injected distiller

The core extractor turns a DDL/OpenAPI artifact into one verbatim EU per schema
object (table+columns / endpoint / type), `structure_type = table_schema`, carrying
its source span. FK/`$ref` edges are produced by a **schema distiller** injected via
`graph_distiller=` — mirroring the code structural distiller — because
`ExtractedDoc` has no edge channel and edges are a separate concern by design.
Rationale: resolves the ABI conflict the review found, and keeps one consistent
"extractor = citable nodes; distiller = edges" story across code and schema.

### 2. Only artifacts, only `extracted` edges — connectors/sampled are OUT

`ingest_from` accepts a DDL file or an OpenAPI/JSON-Schema document (path or bytes).
FK and `$ref` are authoritative → `confidence=extracted`. Live-DB connectors and
sampled Mongo/Redis shapes are excluded (scope-gate + cite-or-abstain, per review).
If a live/sampled source is ever added, it is a separate connector change that
produces a schema **artifact** and hands it to this extractor — never a data read in
core.

### 3. `rag.schema.ingest_from` — graph-required, Python-wired, `${ENV}`-safe

Same fail-loud rule as `rag.code.ingest_from`: raise if no `graph`/`community`
signal. Graph wiring lands in Python (the only wired graph layer). No new
constructor surface; `rag.schema` is a lazy sub-facade. Should a future connector
need credentials, it uses `${ENV}` names expanded at the boundary — never a value in
the signature — but no connector ships here.

## Risks / Trade-offs

- **[Someone expects live-DB ingest from this change]** → explicitly out; documented.
  The verb takes artifacts (files/docs), not connection URLs.
- **[Per-dialect DDL divergence]** → one parser per family with dialect handling;
  parity test pins output; unknown dialect degrades to plain text (never fails).
- **[Topology misattribution]** → far milder than code: FK/`$ref` are `extracted`
  (authoritative), not guessed, so the `structural-code-graph` topology caveat
  barely applies; still, the answer-path `confidence` handling (follow-on) covers it.

## Migration Plan

Additive: new `schema-extractor` capability, `rag.schema` namespace + verb, injected
schema distiller. Depends on `structural-code-graph` landing first. No public
appearance removed.

## Open Questions

- Whether JSON-Schema (standalone) ships alongside OpenAPI in v1 or follows.
- Exact EU granularity for OpenAPI (one EU per endpoint vs per operation vs per
  schema component — lean: per endpoint + per component).
