## Context

§7b makes document structure polymorphic and best-effort: heading tree, code AST,
slide sequence, table schema, thread order, page layout, or none. v3.2's core rule
is that structure is optional and degrades to nothing without blocking retrieval.
This change adds the index that captures whatever structure an `ExtractedDoc`
declares (`structure_type`) into one uniform node shape, building only on the
already-shipped `citenexus.extract.types` (§8).

## Goals / Non-Goals

**Goals:**
- A uniform `StructureNode` shape (`node_id, parent_id, label, kind, eu_ref`)
  regardless of structure type, so downstream retrieval treats all structures
  identically.
- Build a nested heading tree and a flat slide sequence from the extracted blocks.
- Anchor every node to its Evidence Unit via `eu_ref` (`document_id::order`),
  matching the evidence-builder's id scheme.
- Return zero nodes — not an error — whenever there is no usable structure.

**Non-Goals:**
- No code AST / table schema / thread order / page layout builders yet — they
  degrade to zero nodes for now (best-effort, honest, extensible later).
- No retrieval or scoring — this is the index the §10 structure retriever reads,
  not the retriever.
- No mutation of `EvidenceUnit`; nodes only *reference* EUs by id.

## Decisions

- **One uniform node shape across all structure types.** Every node is a
  `StructureNode(node_id, parent_id, label, kind, eu_ref)`. A tree expresses depth
  via `parent_id`; a flat sequence sets `parent_id=None` for all. Downstream code
  never special-cases a structure type to read a node. `kind` is a free `str`
  (e.g. `"heading"`, `"slide"`), not a closed enum, so a new structure type adds
  nodes without widening a shared type.
- **`eu_ref` = `document_id::order`.** A node references the Evidence Unit the
  evidence-builder produced for the same block, so the two changes stay linkable by
  construction. For a heading, `node_id == eu_ref` (the heading is itself a
  `section` EU and the node anchors it).
- **Heading nesting by a level stack.** Walk heading blocks in order, popping a
  `(level, node_id)` stack until its top is a strict ancestor (`level < this`); the
  remaining top is the parent. This yields correct re-parenting when a deeper
  subsection is followed by a shallower sibling (level-3 then level-2 re-attaches to
  the level-1 root, not the level-3 node). Missing `level` defaults to 1 (all
  siblings) — best-effort, never a crash.
- **Empty is normal, not failure.** `structure_type == none`, an unimplemented type,
  or a `heading_tree` with no heading blocks all return `nodes == ()`. The function
  always returns a valid `StructureIndex`; callers never branch on an exception to
  detect "no structure."
- **Frozen pydantic models.** `StructureIndex` and `StructureNode` use
  `ConfigDict(frozen=True, extra="forbid")`, matching the established domain/EU
  style, so the index is a stable, hashable artifact.

## Risks / Trade-offs

- **Best-effort breadth vs. depth.** Only heading_tree and slide_sequence are
  implemented; the other declared types degrade to empty. → Acceptable per §7b
  (structure is optional and never blocks retrieval); the remaining builders are
  additive follow-ups behind the same uniform shape.
- **Level reliability.** Heading nesting trusts the extractor's `level`. A document
  with no levels collapses to a flat list of roots. → Honest degradation, not a
  failure; richer nesting can later fall back to `structure_path`.

## Open Questions

- Whether `kind` should eventually become a closed enum once the full set of
  structure types is implemented — left as a `str` now to keep the shape uniform
  and additive without a core type change.
