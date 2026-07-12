## ADDED Requirements

### Requirement: The vector store can delete a document's rows

The `VectorStore` seam SHALL expose `delete_document(document_id)` that removes
every Evidence-Unit row carrying that `document_id` and leaves all other rows
untouched. The method SHALL be a no-op (no error) when no rows match or when the
underlying table does not yet exist. It SHALL be implemented by every backend
(Lance and Postgres) and by the shared Rust FFI store, and it SHALL be exposed at
parity across the Go, JavaScript, and Python seams so a revoke removes byte-for-byte
the same rows in every port. No separate TextSearch deletion method is required —
the lexical index is derived from the same rows and reflects the deletion once the
rows are gone.

#### Scenario: Deleting one document's rows leaves others intact
- **WHEN** `delete_document(document_id)` is called for a document with rows in the store
- **THEN** all of that document's rows are removed and every other document's rows remain, and a subsequent lexical or vector query returns none of the removed document's Evidence Units

#### Scenario: Deleting an unknown document is a no-op
- **WHEN** `delete_document` is called with a document_id that has no rows, or before the table exists
- **THEN** no rows are removed and no error is raised

### Requirement: The etag manifest can forget a document

The etag manifest SHALL expose an operation that removes a single
`document_id → checksum` entry and persists the change, and it SHALL be a no-op
when the entry is absent. Removing the entry is the commit point of a revoke: while
the entry is present the document is considered logically present.

#### Scenario: Forgetting a document removes its manifest entry
- **WHEN** the manifest is told to forget a document that has an entry
- **THEN** the entry is removed and persisted, and forgetting the same document again does nothing and raises no error
