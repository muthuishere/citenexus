# ingest-pipeline Specification

## Purpose
TBD - created by archiving change ingest-pipeline. Update Purpose after archive.
## Requirements
### Requirement: Universal intake dispatches to the right extractor

`IngestPipeline.ingest` SHALL accept a file path, raw bytes, or raw text, dispatch
to the matching extractor (unknown type → plain), and produce Evidence Units with
the detected document language stamped on each (§8).

#### Scenario: Raw text ingests as evidence

- **WHEN** raw text is ingested with a document id
- **THEN** at least one Evidence Unit is produced, each carrying the document's
  detected language.

#### Scenario: Unknown source falls back to plain

- **WHEN** a source with no recognized type is ingested
- **THEN** it is handled by the plain extractor rather than failing.

### Requirement: Ingest is idempotent by content hash

The pipeline SHALL record each document's content checksum in the etag manifest and
skip re-processing an unchanged document (§4c/§5).

#### Scenario: Re-ingesting unchanged content is skipped

- **WHEN** the same content is ingested twice
- **THEN** the second call reports status `unchanged` and does not re-embed.

### Requirement: Ingest is gated by the declared signals

The pipeline SHALL consult the client's declared signals: `embedding`/`text`
enables embedding + upsert into the leaf vector store; `structure` enables building
and persisting the structure index; any slow-path signal
(`graph`/`community`/`wiki`) enqueues the content hash on the worker (§8, §15).

#### Scenario: Lexical/semantic-only client skips graph and structure work

- **WHEN** a pipeline declared with signals `["embedding","text"]` ingests a document
- **THEN** its Evidence Units are embedded and upserted, no structure index is
  persisted, and nothing is enqueued on the slow-path queue.

#### Scenario: Structure signal persists a structure index

- **WHEN** a pipeline that includes the `structure` signal ingests a document with
  headings
- **THEN** a structure index for that document is persisted under the knowledge layer.

#### Scenario: Slow-path signal enqueues the document

- **WHEN** a pipeline that includes the `graph` signal (with a worker queue) ingests
  a document
- **THEN** the document's content hash is enqueued for slow-path processing.

### Requirement: Ingest persists the raw blob and returns a result

The pipeline SHALL store the raw bytes content-addressed under the raw layer and
return an `IngestResult` with the document id, status, the produced `eu_ids`, and
the unit count.

#### Scenario: Result reports the produced units

- **WHEN** a document yielding two blocks is ingested
- **THEN** the result lists two `eu_ids`, `n_units == 2`, and status `ingested`.

### Requirement: Ingest fulfills vision requests via the injected plugin without changing caller behavior

When a `vision` plugin is configured, `ingest()` (and `ask()` over freshly ingested
content) SHALL internally drive the `vision-orchestration` seam — emit the pending
requests, fulfill them through the injected plugin, and assemble the figure
Evidence Units — with no change to the public call signature. When no `vision`
plugin is configured, ingest SHALL emit no requests and produce no figure Evidence
Units, exactly as today. The injected plugin SHALL be the sole holder of the vision
endpoint's credentials; the pipeline SHALL pass it only `PendingVisionRequest`s.

#### Scenario: ingest() auto-fulfills when a vision plugin is present

- **WHEN** `ingest()` runs on a document with a vision-routed figure and a `vision` plugin is configured
- **THEN** the resulting evidence includes the figure's `EvidenceUnit(type=figure)` and the caller made no extra call

#### Scenario: ingest() without a vision plugin produces no figure units

- **WHEN** `ingest()` runs on the same document with no `vision` plugin configured
- **THEN** ingest completes with no figure Evidence Units and no model call

### Requirement: Ingest has an inverse

The ingest pipeline SHALL support undoing a single document's persisted artifacts —
the inverse of `ingest()`. Given a `document_id`, it SHALL remove that document's
vector rows, its structure index, and its per-document image blobs, and — guarded
by the shared-checksum reference rule — its content-addressed raw blob, then
trigger the graph rebuild and wiki page removal that keep navigation consistent.
The inverse SHALL reuse the same partition prefix scheme and storage backend that
ingest uses, and SHALL be idempotent with respect to already-removed artifacts.

#### Scenario: Undo removes exactly the document's persisted artifacts

- **WHEN** a document is ingested (rows, structure, image blobs, raw blob, manifest entry) and then revoked
- **THEN** the document's rows, structure index, and image blobs are removed, and its raw blob is removed only if no other document shares its checksum

#### Scenario: Undo is idempotent against partially-removed state

- **WHEN** a revoke runs against a document whose artifacts were already partially removed by an earlier interrupted revoke
- **THEN** the remaining artifacts and the manifest entry are removed with no error

