## ADDED Requirements

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
