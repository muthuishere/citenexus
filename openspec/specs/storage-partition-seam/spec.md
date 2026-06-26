# storage-partition-seam Specification

## Purpose
TBD - created by archiving change storage-partition-seam. Update Purpose after archive.
## Requirements
### Requirement: Partition paths resolve to deterministic S3 prefixes

The system SHALL map a `PartitionPath` of any depth to a stable key segment
`<P>` (ordered `level=value` segments joined by `/`) and expose the standard
layer prefixes (`raw`, `extracted`, `knowledge`, `graph`, `vector`, `manifests`,
`eval`) under it (§6b). Resolution MUST NOT assume a fixed number of levels.

#### Scenario: Three-level partition resolves to a stable prefix

- **WHEN** the prefix for layer `raw` is requested for
  `[(org,acme),(product_line,contracts),(product,nda-review)]`
- **THEN** it equals `raw/org=acme/product_line=contracts/product=nda-review`.

#### Scenario: Single-level partition resolves

- **WHEN** the `vector` prefix is requested for `[(workspace,w1)]`
- **THEN** it equals `vector/workspace=w1`.

### Requirement: A backend seam abstracts local filesystem and S3

The system SHALL provide a `StorageBackend` with `put_bytes`, `get_bytes`,
`exists`, `list_prefix`, `delete_prefix`, `put_json`, and `get_json`, plus a
content-addressed `put_blob` that stores bytes under a `sha256` key and returns
that digest. There MUST be at least two interchangeable implementations
(`LocalFsBackend`, `S3Backend`) that satisfy the same contract.

#### Scenario: Bytes round-trip through a backend

- **WHEN** `put_bytes(key, data)` is called and then `get_bytes(key)`
- **THEN** the returned bytes equal `data` and `exists(key)` is true.

#### Scenario: Content-addressed blob is keyed by its sha256

- **WHEN** `put_blob(prefix, data)` is called twice with identical `data`
- **THEN** both calls return the same `sha256` digest and store a single object.

#### Scenario: Deleting a prefix removes everything beneath it

- **WHEN** several objects are written under `raw/org=acme/` and `delete_prefix`
  is called on that prefix
- **THEN** none of those objects remain and `list_prefix` returns empty.

### Requirement: Each leaf partition has its own LanceDB vector store

The system SHALL open or create one LanceDB database per leaf `PartitionPath`
(local path or `s3://…`), upsert Evidence-Unit rows (id + vector + payload), run
vector search returning nearest rows, and drop the leaf. Leaves MUST be
physically separate so deleting one cannot affect another (§6b).

#### Scenario: Upsert then nearest-neighbour search

- **WHEN** two EU rows with distinct vectors are upserted and a query vector close
  to the first is searched with `limit=1`
- **THEN** the single returned row is the first EU.

#### Scenario: Two leaves are isolated

- **WHEN** rows are written into leaf A and leaf B and leaf A is dropped
- **THEN** leaf B still returns its rows.

### Requirement: Manifests persist as JSON and detect changes

The system SHALL persist typed manifests (etag, model, processing) as JSON via the
backend, and the etag manifest SHALL report whether a document's current
ETag/checksum differs from the recorded one (the fast-path change signal, §4c/§5).

#### Scenario: Unchanged checksum is not dirty

- **WHEN** a document's checksum is recorded and the same checksum is checked again
- **THEN** the manifest reports it as unchanged.

#### Scenario: New or changed checksum is dirty

- **WHEN** a checksum differs from the recorded one (or none is recorded)
- **THEN** the manifest reports it as changed.

