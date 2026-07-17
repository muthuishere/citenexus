## ADDED Requirements

### Requirement: Schema extraction yields one verbatim EU per schema object (no edges)

The system SHALL provide core schema extractors (SQL DDL, OpenAPI/JSON-Schema) that
emit one **verbatim**, citable Evidence Unit per schema object — a table (with its
columns), an endpoint, or a type — carrying its source span, using the existing
`StructureType.table_schema`. Extractors live in the Rust core, exposed via
`citenexus_extract`, byte-parity-tested against a Python reference. The extractor
MUST NOT emit graph edges — `ExtractedDoc` has no edge channel; edges are produced
separately (see the schema distiller).

#### Scenario: A table becomes a citable schema EU

- **WHEN** a SQL DDL defining table `accounts` is extracted
- **THEN** an Evidence Unit for `accounts` is emitted with its verbatim definition
- **AND** the structure type is `table_schema`

#### Scenario: An OpenAPI endpoint becomes a citable EU

- **WHEN** an OpenAPI spec with `POST /orders` is extracted
- **THEN** an Evidence Unit for that endpoint is emitted verbatim

### Requirement: Structural edges come from an injected schema distiller

Schema structural edges (foreign keys, OpenAPI `$ref`, type references) SHALL be
produced by a schema distiller injected via the existing `graph_distiller=` seam —
not by the core extractor — and marked `GraphEdge.confidence = extracted` because
they are authoritative (read directly from the schema, not guessed).

#### Scenario: A foreign key is an extracted edge from the distiller

- **WHEN** the injected schema distiller processes a DDL declaring an FK from
  `orders.account_id` to `accounts.id`
- **THEN** it emits an edge between those objects with `confidence = extracted`

### Requirement: `rag.schema.ingest_from` ingests schema artifacts, graph-required

The system SHALL provide `rag.schema.ingest_from(source)` where `source` is a SQL
DDL file or an OpenAPI/JSON-Schema document (a path or bytes) — **not** a live
connection URL. It drives the core extractor + the injected schema distiller. It
MUST raise immediately if the instance has no `graph`/`community` signal declared,
with no partial ingest. Graph wiring is provided in Python (the wired graph layer).

#### Scenario: A DDL file is ingested into schema EUs + extracted edges

- **WHEN** `rag.schema.ingest_from("schema.sql")` runs on a graph-enabled instance
- **THEN** its tables become verbatim schema EUs and its FKs become `extracted` edges

#### Scenario: Missing graph signal fails loud

- **WHEN** `rag.schema.ingest_from(...)` is called with no `graph` signal declared
- **THEN** it raises an error naming the missing signal and ingests nothing

### Requirement: Live-DB connectors and sampled shapes are out of scope

This capability SHALL NOT include live-database connectors (`postgres://`,
`mysql://`, `mongodb://`, `redis://`) or any sampled/synthesized schema shape. Live
connectors are a network-service surface (out of core), and a sampled shape has no
verbatim span to cite and requires reading data. Any future support MUST first
produce a schema **artifact** and hand it to this extractor.

#### Scenario: A connection URL is not accepted here

- **WHEN** a live connection URL is passed to `rag.schema.ingest_from`
- **THEN** it is not treated as an in-core connector (this change ingests artifacts,
  not live connections)

#### Scenario: An unsupported/unknown schema source degrades to plain

- **WHEN** a source no schema extractor recognises is passed
- **THEN** ingestion does not raise; the content is available as plain-text EUs
