# core-domain-types Specification

## Purpose
TBD - created by archiving change core-domain-types. Update Purpose after archive.
## Requirements
### Requirement: Evidence Unit is the atomic retrievable object

The system SHALL provide an `EvidenceUnit` model carrying the fields defined in
§7: `eu_id`, `partition` (a PartitionPath), `document_id`, `type`, `language`,
`text`, optional `page`/`section`/`source_uri`, a `citation`, `entities`, optional
`structure_path`, opaque `acl`, optional `dense_vector`/`sparse_vector`,
`checksum`, and `source_checksum`. An EvidenceUnit MUST be constructible with only
its required identity/content fields; vector and layout fields MUST be optional.

#### Scenario: Minimal Evidence Unit constructs

- **WHEN** an EvidenceUnit is created with `eu_id`, `document_id`, `type=paragraph`,
  `language`, `text`, a `partition`, and a `citation`
- **THEN** construction succeeds and the optional vector fields default to `None`.

#### Scenario: Missing required field is rejected

- **WHEN** an EvidenceUnit is created without `text`
- **THEN** a validation error is raised.

### Requirement: Evidence Unit type is a closed enum

The `EvidenceUnit.type` field SHALL be one of: `paragraph`, `section`, `table`,
`figure`, `image`, `chart`, `diagram`, `code_block`, `ocr_block`, `page_summary`,
`document_summary`, `community_summary` (§7). Any other value MUST be rejected.

#### Scenario: Unknown EU type rejected

- **WHEN** an EvidenceUnit is created with `type="footnote"`
- **THEN** a validation error is raised.

#### Scenario: Known EU type accepted

- **WHEN** an EvidenceUnit is created with `type="community_summary"`
- **THEN** construction succeeds.

### Requirement: Citation carries verifiable provenance

The system SHALL provide a `Citation` model with `page`, `bbox` (a 4-number
`[x0,y0,x1,y1]`), and `passage` (the verbatim source text). `bbox` MUST contain
exactly four numbers when present.

#### Scenario: Citation with bbox

- **WHEN** a Citation is created with `page=12`, `bbox=[120,300,510,380]`, and a
  `passage`
- **THEN** construction succeeds and `bbox` has length 4.

#### Scenario: Malformed bbox rejected

- **WHEN** a Citation is created with `bbox=[1,2,3]`
- **THEN** a validation error is raised.

### Requirement: ACL is carried opaque and never parsed

The `acl` field on EvidenceUnit SHALL accept any caller-supplied value (role list,
matter id, classification label, tuple) verbatim, default to `None`, and be
round-tripped through serialization unchanged. The model MUST NOT impose a schema
on, parse, or interpret `acl` (§7c).

#### Scenario: Arbitrary acl is stored verbatim

- **WHEN** an EvidenceUnit is created with `acl={"roles": ["partner"], "matter": "m7"}`
- **THEN** `eu.acl` equals that exact value and survives a JSON round-trip unchanged.

#### Scenario: acl defaults to None

- **WHEN** an EvidenceUnit is created without an `acl`
- **THEN** `eu.acl` is `None`.

### Requirement: PartitionPath is a variable-depth ordered hierarchy

The system SHALL provide a `PartitionPath` value object: an ordered sequence of
`(level, value)` pairs of **any length** (§6b). It MUST NOT assume a fixed depth
or fixed level names. Two PartitionPaths are equal iff their ordered pairs are
equal. A PartitionPath MUST serialize to and deserialize from a stable form
losslessly.

#### Scenario: Three-level and one-level paths both valid

- **WHEN** a PartitionPath is built from `[(org,acme),(product_line,contracts),(product,nda-review)]`
  and another from `[(workspace,w1)]`
- **THEN** both construct successfully and report depths 3 and 1 respectively.

#### Scenario: Equality is order-sensitive on pairs

- **WHEN** two PartitionPaths have the same `(level,value)` pairs in the same order
- **THEN** they compare equal; reordering any pair makes them unequal.

### Requirement: PartitionPath supports prefix addressing

A PartitionPath SHALL expose whether it is a prefix of (an ancestor of) another
PartitionPath, so a query scope can target any prefix of the hierarchy (§6b).

#### Scenario: Prefix is recognized

- **WHEN** path `A=[(org,acme),(product_line,contracts)]` is tested against
  `B=[(org,acme),(product_line,contracts),(product,nda-review)]`
- **THEN** `A` is reported as a prefix of `B`, and `B` is not a prefix of `A`.

#### Scenario: Divergent path is not a prefix

- **WHEN** path `[(org,acme),(product_line,hr)]` is tested against
  `[(org,acme),(product_line,contracts),(product,nda)]`
- **THEN** it is reported as NOT a prefix.

### Requirement: Evidence is expressed as structured signals, not a scalar

The system SHALL provide an `EvidenceSignals` model with `supporting_sources`,
`distinct_documents`, `retrieval_score_spread`, `all_claims_verified`,
`unsupported_claims_removed`, `conflicts_detected`, `languages_in_evidence`, and
`decision` (§12). There MUST be no scalar `confidence` field anywhere in the
domain models. `decision` MUST be one of `answered`, `refused`, `partial`.

#### Scenario: Signals capture why the system answered

- **WHEN** an EvidenceSignals is created with `supporting_sources=3`,
  `distinct_documents=2`, `all_claims_verified=True`, `decision="answered"`
- **THEN** construction succeeds and those values are readable.

#### Scenario: No scalar confidence exists

- **WHEN** the EvidenceSignals (and Result) model fields are inspected
- **THEN** there is no field named `confidence`.

#### Scenario: Invalid decision rejected

- **WHEN** an EvidenceSignals is created with `decision="maybe"`
- **THEN** a validation error is raised.

### Requirement: SourceRef keeps the cited passage verbatim in its source language

The system SHALL provide a `SourceRef` model (a Result `sources` entry) with
`document`, `page`, `passage`, `passage_language`, optional `bbox`, optional
`source_uri`, and an optional `translation` (§16, §11). The `passage` MUST be the
verbatim source text; `translation`, when present, is a separate marked field that
MUST NOT replace `passage`.

#### Scenario: Untranslated source keeps verbatim passage

- **WHEN** a SourceRef is created with an English `passage` and no `translation`
- **THEN** `translation` is `None` and `passage` is unchanged.

#### Scenario: Translation is additive, never destructive

- **WHEN** a SourceRef has a French `passage` (`passage_language="fr"`) and an
  English `translation`
- **THEN** both fields are present and distinct; `passage` still holds the verbatim
  French text.

### Requirement: TrustMode enumerates the three modes

The system SHALL provide a `TrustMode` enum with exactly `strict`, `normal`, and
`exploratory` members (§14).

#### Scenario: Trust modes are exactly these three

- **WHEN** the members of `TrustMode` are listed
- **THEN** they are exactly `strict`, `normal`, `exploratory`.

### Requirement: Result models a grounded answer with a reproducible provenance chain

The system SHALL provide a `Result` model with `answer`, `answer_language`, `mode`
(a TrustMode), `evidence` (EvidenceSignals), `claims` (each with `claim`,
`supported`, `sources`), `sources` (list of SourceRef), `missing_evidence`,
`conflicts`, and `provenance` — where each provenance entry resolves a claim
through `evidence_unit → page+bbox → document_id → s3_object → checksum →
produced_by` (§16). `answer_language` records the query language `L`; it is
independent of `languages_in_evidence`.

#### Scenario: Result exposes answer language distinct from evidence languages

- **WHEN** a Result has `answer_language="ta"` while
  `evidence.languages_in_evidence=["en"]`
- **THEN** both are readable and independent (a Tamil answer over English evidence).

#### Scenario: Provenance entry forms a full chain

- **WHEN** a Result provenance entry is created for a claim referencing an
  `evidence_unit`, `page`, `bbox`, `document_id`, `s3_object`, `checksum`, and a
  `produced_by` stamp
- **THEN** every link in the chain is present and readable.

### Requirement: Domain models round-trip losslessly through JSON

Every domain model SHALL serialize to JSON and deserialize back to an equal
object with no loss of data — EvidenceUnit, PartitionPath, EvidenceSignals,
SourceRef, and Result all round-trip losslessly.

#### Scenario: Evidence Unit JSON round-trip

- **WHEN** an EvidenceUnit with `acl`, `structure_path`, and a citation is
  serialized to JSON and parsed back
- **THEN** the resulting EvidenceUnit equals the original.

#### Scenario: Result JSON round-trip

- **WHEN** a fully-populated Result is serialized to JSON and parsed back
- **THEN** the resulting Result equals the original.

