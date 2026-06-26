## Why

Structure is the fifth retrieval signal (§10), but real documents disagree about
what "structure" *is* — a Word doc is a heading tree, a deck is a slide sequence,
many files have none at all. v3.2 makes the structure signal best-effort and
source-type-aware (§7b): never assumed to be a tree, optional per document, and
degrading to nothing without blocking retrieval. The library needs a uniform,
honest index that captures whatever structure exists and stays empty when it
doesn't — without ever treating "no structure" as a failure.

## What Changes

- Add a frozen `StructureIndex(document_id, structure_type, nodes)` and a uniform
  `StructureNode(node_id, parent_id, label, kind, eu_ref)` — one node shape for
  every structure type.
- Add `build_structure(doc) -> StructureIndex`, dispatching on `doc.structure_type`:
  a `heading_tree` nests its heading blocks by `level` with correct parent links; a
  `slide_sequence` yields one flat node per slide in document order.
- Each node's `eu_ref` resolves to the Evidence Unit that anchors it, using the
  same `document_id::order` id scheme as the evidence-builder.
- Every other `structure_type` — including `none`, and a heading document that
  carries no headings — yields **zero nodes**. An empty index is a normal,
  expected outcome, never an error.

## Capabilities

### New Capabilities
- `structure-index`: the best-effort, source-type-aware Structure Index — uniform
  node shape across types, heading-tree and slide-sequence builders, EU-anchored
  `eu_ref`s, and the "no structure ⇒ empty, not failure" guarantee (§7b).

### Modified Capabilities
<!-- None: purely additive. ExtractedDoc/ExtractedBlock/StructureType/BlockKind
(§8) already ship and are reused unchanged. -->

## Impact

- New module `src/trustrag/evidence/structure.py`, building only on the existing
  `trustrag.extract.types` (§8). `evidence/__init__.py` is unchanged; the module is
  imported by full path.
- New tests under `tests/evidence/test_structure.py`. No new dependencies, no
  public-API verb change (this feeds the §10 structure retriever, not a verb).
