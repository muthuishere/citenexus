## ADDED Requirements

### Requirement: A re-ingest reclaims the blob it supersedes

When ingest replaces a document's recorded checksum, it SHALL record the retired
checksum durably BEFORE reclaiming the blob it names, and SHALL then delete that
blob subject to the same reference guard revoke uses — only when no other
document currently owns the checksum.

The ordering SHALL be such that no window exists in which a raw blob is both
undeleted and unreachable from the manifest. An ingest interrupted at any point
SHALL leave the retired checksum recorded, so a later ingest or revoke completes
the reclamation; re-running SHALL be idempotent.

Recording a checksum that the document previously retired SHALL clear it from the
retired set, so a document's current checksum is never eligible for reclamation.

#### Scenario: A re-ingest does not strand the previous blob

- **GIVEN** a document ingested, then re-ingested with different bytes
- **THEN** only the current raw blob remains in storage for that document

#### Scenario: A previous blob another document owns is kept

- **GIVEN** a document whose previous bytes are also the current bytes of a second document
- **WHEN** the first document is re-ingested with different bytes
- **THEN** the shared raw blob is preserved

#### Scenario: Returning to a previous version does not delete the live blob

- **GIVEN** a document ingested as A, re-ingested as B, then re-ingested as A again
- **THEN** the blob for A remains in storage
