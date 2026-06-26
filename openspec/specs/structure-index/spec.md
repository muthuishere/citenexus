# structure-index Specification

## Purpose
TBD - created by archiving change structure-index. Update Purpose after archive.
## Requirements
### Requirement: Structure is captured in a uniform node shape

The system SHALL build a `StructureIndex` carrying the document's `document_id`,
its `structure_type`, and a tuple of `StructureNode`s. Every node SHALL have the
same shape — `node_id`, `parent_id`, `label`, `kind`, and `eu_ref` — regardless of
the document's structure type, so downstream retrieval reads every structure
identically. Each node's `eu_ref` SHALL reference the Evidence Unit that anchors it
using the `f"{document_id}::{order}"` id scheme.

#### Scenario: Node shape is uniform across structure types
- **WHEN** indices are built for a `heading_tree` document and a `slide_sequence` document
- **THEN** every node in both indices has exactly the fields `node_id`, `parent_id`, `label`, `kind`, `eu_ref`

#### Scenario: A node links to its Evidence Unit
- **WHEN** a heading block at `order=2` in document `doc1` is indexed
- **THEN** its node's `eu_ref` is `doc1::2`

### Requirement: A heading tree nests headings by level

For a document whose `structure_type` is `heading_tree`, the system SHALL create one
node per heading block (non-heading blocks are not nodes) and SHALL set each node's
`parent_id` to the nearest preceding heading of a shallower `level`, or `None` for a
top-level heading. A shallower heading following a deeper one SHALL re-parent up to
its correct ancestor.

#### Scenario: Headings nest by level with correct parents
- **WHEN** a document has headings `Agreement`(L1), `5. Confidentiality`(L2), `5.2 Exceptions`(L3), `6. Term`(L2)
- **THEN** `Agreement` is a root, `5. Confidentiality`'s parent is `Agreement`, `5.2 Exceptions`'s parent is `5. Confidentiality`, and `6. Term`'s parent re-parents back to `Agreement`

#### Scenario: Non-heading blocks are not nodes
- **WHEN** a heading_tree document interleaves heading and paragraph blocks
- **THEN** only the heading blocks become nodes

### Requirement: A slide sequence yields one flat node per slide in order

For a document whose `structure_type` is `slide_sequence`, the system SHALL create
exactly one node per slide block, in document order, each with `parent_id == None`.

#### Scenario: One node per slide, in order, all top-level
- **WHEN** a deck `deck` has slide blocks `Title`, `Agenda`, `Summary` at orders 0..2
- **THEN** the index has three nodes labelled `Title`, `Agenda`, `Summary` with `eu_ref`s `deck::0`, `deck::1`, `deck::2`, and every node has `parent_id == None`

### Requirement: No usable structure yields an empty index, not a failure

The system SHALL return a valid `StructureIndex` with zero nodes whenever there is
no usable structure — when `structure_type` is `none`, when the structure type has
no builder, or when a `heading_tree` document carries no heading blocks. An empty
index SHALL be a normal, expected outcome and SHALL NOT raise an error.

#### Scenario: structure_type none yields zero nodes
- **WHEN** `build_structure` runs over a document whose `structure_type` is `none`
- **THEN** it returns a `StructureIndex` with `nodes == ()` and the same `structure_type`, without raising

#### Scenario: A heading document with no headings yields zero nodes
- **WHEN** a `heading_tree` document contains only paragraph blocks
- **THEN** the index has `nodes == ()` and no error is raised

