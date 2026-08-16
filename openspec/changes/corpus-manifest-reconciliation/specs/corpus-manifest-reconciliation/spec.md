## ADDED Requirements

### Requirement: The corpus manifest is caller-authored and versioned

The system SHALL accept a corpus manifest as an input declared by the caller, not
derived from the index. A manifest SHALL carry its own version identifier and one
entry per declared document version, each naming a `document_id`, a file SHA-256,
a version label, whether that version is current, and optionally a source URI and
an effective date.

A manifest SHALL declare at most one current version per `document_id`, and the
system SHALL reject a manifest that declares two.

The system SHALL NOT provide any means of generating a manifest from the live
index: such a manifest could not disagree with the index, which would void the
diagnostic.

#### Scenario: A manifest declares a document version

- **WHEN** a manifest entry names a `document_id`, a SHA-256, and a version label
- **THEN** the manifest reports that document as declared, with that hash as its current content

#### Scenario: Two current versions of one document are rejected

- **WHEN** a manifest declares two entries for the same `document_id` both marked current
- **THEN** constructing the manifest raises an error

### Requirement: Reconcile reports three disjoint sets

The system SHALL provide a reconciliation pass that compares the declared corpus
against live index state and returns a report containing three sets:

- **orphans** — documents present in the index whose `document_id` the manifest
  does not declare in any version.
- **missing** — documents the manifest declares current that are not present in
  the index.
- **drifted** — documents present in both whose indexed content hash does not
  match the declared current hash.

The three sets SHALL be disjoint: no `document_id` may appear in more than one.

The report SHALL identify the partition it covers, the manifest version it was
computed against, and the time it was computed.

#### Scenario: An index matching its manifest reports clean

- **WHEN** every indexed document is declared current with the indexed hash
- **THEN** all three sets are empty and the report reports itself clean

#### Scenario: An undeclared document is an orphan

- **GIVEN** a document that was ingested but appears nowhere in the manifest
- **WHEN** reconciliation runs
- **THEN** that `document_id` is in `orphans` and in neither other set

#### Scenario: A declared document that never landed is missing

- **GIVEN** a document declared current in the manifest whose ingest did not complete
- **WHEN** reconciliation runs
- **THEN** that `document_id` is in `missing` and in neither other set

#### Scenario: A changed source is drift

- **GIVEN** an indexed document whose declared current hash differs from its indexed hash
- **WHEN** reconciliation runs
- **THEN** that `document_id` is in `drifted`, with both hashes reported, and in neither other set

#### Scenario: The sets never overlap

- **WHEN** reconciliation runs against any manifest
- **THEN** no `document_id` appears in more than one of orphans, missing, drifted

### Requirement: Enumeration unions the logical and physical records

Live index state SHALL be enumerated by unioning the etag manifest
(`document_id → checksum`, the logical presence record and the revoke commit
point) with a scan of the vector store (rows carrying `document_id` and
`checksum`, the physical record). A document known to either source SHALL count
as indexed.

This is required so that half-states are visible: an interrupted revoke or an
out-of-band write can leave retrievable rows with no manifest entry, and a
partition with neither the `embedding` nor the `text` signal declared has no
vector rows at all.

#### Scenario: A document with rows but no manifest entry is still seen

- **GIVEN** vector rows for a `document_id` that the etag manifest does not record
- **WHEN** reconciliation runs against a manifest that does not declare it
- **THEN** it is reported as an orphan rather than being invisible

#### Scenario: A partition with no vector rows still enumerates

- **GIVEN** a partition ingested without the `embedding` or `text` signal
- **WHEN** reconciliation runs
- **THEN** documents recorded in the etag manifest are treated as indexed

### Requirement: A superseded version is drift, not an orphan

When the manifest declares a `document_id` but marks the version whose hash is
indexed as not current, the system SHALL classify that document as drifted and
SHALL identify the superseded version. It SHALL NOT classify it as an orphan.

A drift finding SHALL distinguish a superseded declared version from an indexed
hash that matches no declared version at all.

#### Scenario: An indexed prior version is drift

- **GIVEN** a manifest declaring v2 current and v1 not current, with v1 indexed
- **WHEN** reconciliation runs
- **THEN** the document is in `drifted`, not in `orphans`
- **AND** the finding names v1 as the superseded version that is indexed

#### Scenario: An unknown indexed hash is distinguishable from supersession

- **GIVEN** an indexed hash matching no declared version of a declared document
- **WHEN** reconciliation runs
- **THEN** the drift finding records that the indexed content matches no declared version

### Requirement: Reconciliation is read-only and idempotent

Reconciliation SHALL NOT modify the index or any evidence layer — not the vector
store, the raw layer, the knowledge layer, the graph, the wiki, or the etag
manifest — and SHALL NOT delete anything under any circumstances.

Reconciliation SHALL be idempotent: two consecutive runs against the same
manifest and the same index SHALL produce equivalent reports.

The system SHALL offer a mode in which reconciliation performs no writes at all.

#### Scenario: Reconciliation changes no evidence

- **WHEN** reconciliation runs against an index with orphans, missing and drifted documents
- **THEN** every evidence layer is byte-for-byte unchanged afterwards

#### Scenario: Reconciliation repeats identically

- **WHEN** reconciliation runs twice with no intervening change
- **THEN** the two reports contain the same three sets

### Requirement: Remediation is a separate call that removes orphans only

The system SHALL provide remediation as an explicit call that consumes a
reconciliation report. It SHALL remove only the report's orphans, and SHALL do so
through the existing document revoke path so a removed document leaves nothing
behind in any layer.

Remediation SHALL NOT act on `missing` or on `drifted`: those require an ingest
and a re-ingest respectively, which need source bytes the library does not hold.

No deletion SHALL occur as a side effect of reconciliation.

#### Scenario: Orphans are removed through revoke

- **GIVEN** a report containing an orphan
- **WHEN** remediation runs
- **THEN** the orphan is revoked through the same path as `delete()` and a follow-up reconciliation reports no orphans

#### Scenario: Missing and drifted documents survive remediation

- **GIVEN** a report containing missing and drifted documents
- **WHEN** remediation runs
- **THEN** those documents are untouched and still appear in the follow-up report

#### Scenario: Remediating a stale report is safe

- **GIVEN** a report whose orphan was already removed
- **WHEN** remediation runs
- **THEN** the outcome for that document is recorded as absent and nothing else changes

### Requirement: Reports are stamped into an append-only audit stream

The system SHALL append each reconciliation and each remediation to an
append-only audit stream stored under the partition, so that "the index matched
the agreed corpus at time T" is a retained artifact rather than a claim. Existing
audit records SHALL never be rewritten or removed.

#### Scenario: A reconciliation is retained

- **WHEN** reconciliation runs twice
- **THEN** the audit stream contains both records, in order, with the earlier one unmodified

#### Scenario: A remediation is retained

- **WHEN** remediation removes an orphan
- **THEN** the audit stream records what was removed

### Requirement: The report states its own scope

The report SHALL carry, as part of its own content, the statement that it is
document-keyed and therefore does not detect byte-level residue in the raw or
knowledge layers, nor objects written into a shared prefix by anything other than
this library.

An empty report SHALL mean "no document-level disagreement with the declared
corpus" and SHALL NOT be presented as proof that storage is clean.

#### Scenario: A clean report carries its limitation

- **WHEN** reconciliation returns an empty report
- **THEN** the report still states that its scope is document-level only
