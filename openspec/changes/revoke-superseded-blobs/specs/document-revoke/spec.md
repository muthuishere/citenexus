## ADDED Requirements

### Requirement: Revoke removes every raw blob the document ever wrote

A revoke SHALL delete the content-addressed raw blob for the document's current
checksum **and** for every checksum that document previously held and has since
retired by re-ingest. After a successful revoke no bytes written on behalf of
that `document_id` SHALL remain in the raw layer.

To make this possible the system SHALL retain, per document, the checksums it has
retired. Retirement SHALL be recorded at the moment the current checksum is
replaced, so the reference to the retired blob is never severed.

#### Scenario: A superseded raw blob does not survive a revoke

- **GIVEN** a document ingested, then re-ingested with different bytes
- **WHEN** the document is revoked
- **THEN** neither the current nor the superseded raw blob remains in storage
- **AND** the call still reports status `deleted`

#### Scenario: Every superseded blob is removed, not just the most recent

- **GIVEN** a document re-ingested several times with different bytes each time
- **WHEN** the document is revoked
- **THEN** no raw blob written for that document remains in storage

#### Scenario: A superseded blob another document currently owns survives

- **GIVEN** a document whose superseded checksum is the CURRENT checksum of a second document
- **WHEN** the first document is revoked
- **THEN** the shared raw blob is preserved and the second document remains answerable

## MODIFIED Requirements

### Requirement: Shared content-addressed raw blobs are reference-guarded

Because raw blobs are content-addressed and shared by documents with identical
bytes, the system SHALL delete a raw blob ONLY when no other document
**currently** owns that checksum. A retired (superseded) reference SHALL NOT
count as ownership: those bytes are dead for their own document too, so only a
current reference keeps a blob alive. When another document currently shares the
checksum, the raw blob SHALL be preserved and the surviving document SHALL remain
fully answerable with an intact `raw_uri`.

The system SHALL NOT delete a raw blob on the basis of it being unreferenced by
the manifest. Deletion SHALL be justified positively — the document being revoked
recorded writing that checksum — so the operation is safe on a bucket shared with
other partitions, tenants, or tools.

#### Scenario: A shared raw blob survives while another owner remains

- **WHEN** two documents are ingested from identical bytes (one shared raw blob) and one is revoked
- **THEN** the shared raw blob is preserved and the surviving document is still answerable

#### Scenario: The last owner's raw blob is removed

- **WHEN** the last document currently owning a given checksum is revoked
- **THEN** that raw blob is deleted

#### Scenario: Blobs belonging to no known document are left alone

- **WHEN** the raw layer contains bytes that no manifest entry references
- **THEN** a revoke does not delete them
