## Why

CiteNexus already ingests documents and (via `structural-code-graph`) code. The
next structural source is a **schema artifact** — a SQL DDL file or an
OpenAPI/JSON-Schema document. Users want to point CiteNexus at a schema and ask
grounded questions about its *shape* ("which tables reference `accounts`?", "what
does `POST /orders` accept?").

This is **schema/shape only, never row data**, and — critically — restricted to
schema **artifacts you already have** (a `.sql` dump, an `openapi.json`), not live
database connections. A schema artifact is citable and its relationships (FK,
`$ref`) are **deterministic, extracted** edges — the ideal consumer of
`GraphEdge.confidence=extracted` from `structural-code-graph`.

## What Changes

- **New: schema-object extractors in the Rust core.** Deterministic parsers for SQL
  DDL and OpenAPI/JSON-Schema emit one verbatim, citable Evidence Unit per schema
  object (a table with its columns, an endpoint, a type), reusing the existing
  `StructureType.table_schema` (no new structure type). Exposed via
  `citenexus_extract`; consumed by all SDKs at parity — same family as `code.rs`.
  **The extractor emits EUs only, no edges** — `ExtractedDoc` has no edge channel,
  and (like `structural-code-graph`) edges are a separate concern.
- **New: an injected schema distiller** that reads the same DDL/OpenAPI and emits
  the structural edges (FK, `$ref`, type reference) as `confidence=extracted`, into
  the graph via the existing `graph_distiller=` seam — exactly how the code
  structural distiller works. Ships as library/example code, not the core extractor.
- **New: `rag.schema.ingest_from(source)` intake verb.** `source` is a **DDL file
  or an OpenAPI/JSON-Schema document** (a path or bytes) — not a live connector.
  It drives the core extractor + the injected distiller. Like `rag.code.ingest_from`
  it **requires the `graph` signal** (raises if absent, no partial ingest). Graph
  wiring is **Python only** for now (Go/JS graph seam is unwired — a later change).
- **Explicitly NOT in this change (moved out):** live-database connectors
  (`postgres://`, `mysql://`, `mongodb://`, `redis://`) and any **sampled** shape.
  Live connectors are a network-service surface (scope-gate: OUT of core), and a
  sampled Mongo/Redis shape is **synthesized, has no verbatim span, and reading
  samples is reading data** — it fails cite-or-abstain. Those belong to a separate
  connector change/consumer repo, not here.

## Capabilities

### New Capabilities
- `schema-extractor`: core deterministic extractors (SQL DDL / OpenAPI / JSON-
  Schema **files/docs**) → one verbatim EU per schema object (reusing
  `table_schema`); an injected schema distiller that emits FK/`$ref` edges as
  `extracted`; and the `rag.schema.ingest_from(file|doc)` intake verb (graph-
  required, Python-wired).

### Modified Capabilities
- (none change requirements — reuses `GraphEdge.confidence`, the `graph_distiller=`
  seam, `table_schema`, and the typed-intake-verb pattern from
  `structural-code-graph`.)

## Impact

- **Depends on `structural-code-graph`** — reuses `confidence`, the injected-
  distiller pattern, `table_schema`, and the typed-intake-verb + graph-required
  rule.
- **Rust core:** new `rust/src/extract/schema_sql.rs` + `schema_openapi.rs`
  (EU-only, no edges) in `citenexus_extract`; parity test vs a Python reference.
- **Python:** `rag.schema` namespace (lazy sub-facade, no new constructor surface);
  the injected schema distiller; graph wiring.
- **Safety:** navigate-not-cite; only schema-artifact structure is ingested, cited
  verbatim; FK/`$ref` edges are `extracted` (deterministic). Topology-question
  caveat is far milder than code (edges are authoritative, not guessed).
- **0.x:** additive (new namespace + verb + extractors); no public appearance
  removed.
