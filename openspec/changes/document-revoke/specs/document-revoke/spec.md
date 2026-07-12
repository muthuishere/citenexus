## ADDED Requirements

### Requirement: A document can be surgically revoked

The system SHALL provide `delete(document_id)` (alias `revoke`) on the client that
removes exactly one previously-ingested document and every artifact derived from
it: its Evidence-Unit vector rows, its per-document image blobs and structure
index, and its manifest entry. After a successful revoke, the document's evidence
SHALL NOT be retrievable and SHALL NOT be citable by `ask()`, while every other
document SHALL remain intact and answerable.

#### Scenario: A revoked document is no longer retrievable or citable
- **WHEN** two documents are ingested and one is revoked by its `document_id`
- **THEN** `ask()` no longer retrieves or cites the revoked document, and the other document is still retrieved, answered, and cited normally

#### Scenario: Revoke reports what it did
- **WHEN** an existing document is revoked
- **THEN** the call returns a status of `deleted` together with the removed Evidence-Unit ids

### Requirement: Revoke is idempotent

Revoking an absent or already-revoked document SHALL be a no-op that does not
error. The system SHALL distinguish the two outcomes by returning a status of
`deleted` when the document existed and `absent` otherwise.

#### Scenario: Double revoke does not error
- **WHEN** a document is revoked and then revoked again with the same `document_id`
- **THEN** the second call returns status `absent` and raises no error

### Requirement: Shared content-addressed raw blobs are reference-guarded

Because raw blobs are content-addressed and shared by documents with identical
bytes, the system SHALL delete a raw blob (and clear the checksum's slow-path
queue/processing state) ONLY when no other document still owns that checksum. When
another document shares the checksum, the raw blob SHALL be preserved and the
surviving document SHALL remain fully answerable with an intact `raw_uri`.

#### Scenario: A shared raw blob survives while another owner remains
- **WHEN** two documents are ingested from identical bytes (one shared raw blob) and one is revoked
- **THEN** the shared raw blob is preserved and the surviving document is still answerable

#### Scenario: The last owner's raw blob is removed
- **WHEN** the last document owning a given checksum is revoked
- **THEN** that raw blob is deleted and the checksum's slow-path state is cleared

### Requirement: Removal order is resumable

The system SHALL remove derived artifacts (vector rows, structure, image blobs, and
the guarded raw blob / graph / wiki) BEFORE removing the document's etag-manifest
entry, so that the manifest entry is the last write. A revoke interrupted before
the manifest entry is removed SHALL leave the document logically present, so that
re-running the revoke completes cleanly and idempotently.

#### Scenario: An interrupted revoke re-runs cleanly
- **WHEN** a revoke is interrupted after some artifacts are removed but before the manifest entry is removed
- **THEN** re-running the revoke removes the remaining artifacts and the manifest entry with no error and no orphaned, still-retrievable evidence

### Requirement: Navigation reflects a revoke

When the `graph` (or `community`) signal is declared, the system SHALL rebuild the
corpus graph after a revoke so it contains no nodes or edges derived from the
removed document. When the `wiki` signal is declared, the system SHALL remove the
document's wiki page(s) and rewrite the wiki index so navigation resolves only to
surviving evidence.

#### Scenario: Graph and wiki no longer point at revoked evidence
- **WHEN** a document is revoked in a store that has graph and wiki signals enabled
- **THEN** the rebuilt graph contains nothing derived from that document and the wiki index no longer lists its page
