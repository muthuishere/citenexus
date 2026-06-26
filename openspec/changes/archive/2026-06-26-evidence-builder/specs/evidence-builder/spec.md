## ADDED Requirements

### Requirement: Each non-empty block becomes one Evidence Unit

The system SHALL map each `ExtractedBlock` of an `ExtractedDoc` to exactly one
`EvidenceUnit`, preserving document order. The `eu_id` SHALL be
`f"{document_id}::{order}"`. Each Evidence Unit's `document_id`, `source_uri`, and
the caller-supplied `partition` and `language` SHALL be set from the document and
call arguments. The system SHALL skip blocks whose text is empty or whitespace-only,
emitting no Evidence Unit for them. The mapping SHALL be pure and deterministic:
the same document and arguments produce equal Evidence Units every time.

#### Scenario: Blocks map to ordered Evidence Units with the id scheme
- **WHEN** `build_evidence_units` runs over a document `nda_2026` whose blocks have `order` 0 and 7
- **THEN** it returns two Evidence Units whose `eu_id`s are `nda_2026::0` and `nda_2026::7` in that order

#### Scenario: Empty and whitespace-only blocks are skipped
- **WHEN** a document's blocks are `["real", "", "   ", "also real"]` at orders 0..3
- **THEN** only the orders 0 and 3 Evidence Units are produced

#### Scenario: Language, partition, and source are stamped on each unit
- **WHEN** `build_evidence_units(doc, partition=p, language="de")` runs for a document with a `source_uri`
- **THEN** every returned unit has `language == "de"`, `partition == p`, and the document's `source_uri`

#### Scenario: An empty document yields no units
- **WHEN** `build_evidence_units` runs over a document with no blocks
- **THEN** it returns an empty list

### Requirement: BlockKind maps to EUType by a closed table

The system SHALL map each `BlockKind` to an `EUType` by a total, closed table:
`paragraph`→`paragraph`, `heading`→`section`, `table`→`table`, `code`→`code_block`,
`image`→`image`, `slide`→`page_summary`, `thread_turn`→`paragraph`,
`ocr_block`→`ocr_block`.

#### Scenario: Every BlockKind resolves to its EUType
- **WHEN** a single-block document is built for each `BlockKind`
- **THEN** the unit's `type` is the mapped `EUType` (e.g. `heading`→`section`, `code`→`code_block`, `slide`→`page_summary`, `thread_turn`→`paragraph`, `ocr_block`→`ocr_block`)

### Requirement: Citation carries the verbatim passage with page and bbox

The system SHALL build each Evidence Unit's `Citation` with `passage` set to the
block's verbatim text and with the block's `page` and `bbox`. The Evidence Unit's
own `text` SHALL equal the verbatim block text. The block's `structure_path` SHALL
be carried onto the Evidence Unit unchanged.

#### Scenario: Citation is bbox-faithful and verbatim
- **WHEN** a block has text `"The employee shall not disclose..."`, `page=12`, and `bbox=(120,300,510,380)`
- **THEN** the unit's `citation.passage` equals that exact text, `citation.page == 12`, `citation.bbox == (120,300,510,380)`, and the unit's `text` equals the same verbatim text

#### Scenario: structure_path is carried through
- **WHEN** a block carries `structure_path=("Agreement","5. Confidentiality","5.2")`
- **THEN** the unit's `structure_path` equals `("Agreement","5. Confidentiality","5.2")`

### Requirement: Partition and acl are carried verbatim, never enforced

The system SHALL carry the caller-supplied `partition` and opaque `acl` onto every
Evidence Unit without parsing, inspecting, or enforcing them (§7c). When no `acl`
is supplied it SHALL default to `None`. The `acl` SHALL be carried by identity — the
same object the caller passed in.

#### Scenario: acl is carried opaque by identity
- **WHEN** `build_evidence_units(..., acl={"roles":["partner"],"matter":"m7"})` runs
- **THEN** each unit's `acl` is the exact same object passed in, unmodified

#### Scenario: acl defaults to None
- **WHEN** `build_evidence_units` is called without an `acl`
- **THEN** each unit's `acl` is `None`
