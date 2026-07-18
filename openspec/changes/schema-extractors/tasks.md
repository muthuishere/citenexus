## 1. Schema-object extractors — Rust core (EU-only, no edges)

- [x] 1.1 Implement `rust/src/extract/schema_sql.rs` (DDL): one verbatim EU per
      table (+columns), `structure_type = table_schema` (reuse existing; do NOT add
      `db_schema`/`api_schema`).
- [x] 1.2 Implement `rust/src/extract/schema_openapi.rs`: one EU per endpoint /
      component, verbatim.
- [x] 1.3 Wire both into `citenexus_extract` dispatch; recognise `.sql` /
      `openapi.json|yaml`; unknown → plain fallback.
- [x] 1.4 Python reference impl + red→green parity test: table EU; OpenAPI endpoint
      EU. Extractor emits NO edges.

## 2. Injected schema distiller (edges) — Python

- [x] 2.1 Implement a schema distiller (injected via `graph_distiller=`, like the
      code structural distiller) that reads the DDL/OpenAPI and emits FK / `$ref` /
      type-reference edges as `confidence=extracted`.
- [x] 2.2 Red→green: a DDL FK → an `extracted` edge between the right table EUs; an
      OpenAPI `$ref` → an `extracted` edge; every edge endpoint resolves to a real
      schema EU.

## 3. `rag.schema.ingest_from(file|doc)` verb — Python

- [x] 3.1 Add the `rag.schema` namespace + `ingest_from(source)` verb: accept a DDL
      file or OpenAPI/JSON-Schema doc (path or bytes). Lazy sub-facade, no new
      constructor surface.
- [x] 3.2 Fail-loud: raise if no `graph`/`community` signal — name it, ingest
      nothing. Test it.
- [x] 3.3 Drive extractor + injected distiller + graph build (Python-wired).
- [x] 3.4 Red→green: DDL file → schema EUs + extracted FK edges; a connection URL is
      NOT treated as an in-core connector; unknown source degrades to plain.

## 4. Integration & guardrails

- [x] 4.1 End-to-end: ingest a DDL + an OpenAPI doc, ask "which tables reference X" /
      "what does POST /orders accept" → cited schema EUs; FK/`$ref` edges route.
- [x] 4.2 Confirm dependency on `structural-code-graph` (confidence + injected-
      distiller pattern + `table_schema`) is satisfied first.
- [x] 4.3 `cargo test` (core + parity), Python `task lint`/`typecheck`/`test` green.
- [x] 4.4 Update `docs/SPEC-v6.md` / `docs/SPEC-PORTS-v1.md`: schema **artifact**
      extractors in core (EU-only); edges via injected distiller; live connectors +
      sampled shapes explicitly OUT (separate change/consumer).

## 5. Follow-on (NOT here — recorded for scope clarity)

- [ ] 5.1 Live-DB / sampled connectors as a SEPARATE change or consumer repo: a
      connector reads schema and produces an artifact for this extractor; `${ENV}`
      creds; never a data read in core.
- [ ] 5.2 Go/JS schema graph wiring (after the Go/JS graph seam exists).
