"""Structure Index — best-effort, source-type-aware document structure (spec §7b).

Structure is *polymorphic and optional*: a Word doc is a heading tree, a deck is a
slide sequence, code is an AST, a thread is an ordered turn list — and many
documents have no usable structure at all. The index never assumes a tree and
never blocks ingestion: when a document's ``structure_type`` is ``none`` (or a
heading document carries no headings), ``build_structure`` returns an index with
**zero nodes** — a normal, expected outcome, not a failure.

Whatever the source type, nodes share one uniform shape
(``node_id, parent_id, label, kind, eu_ref``) so downstream retrieval treats every
structure identically. Each node's ``eu_ref`` resolves to the Evidence Unit that
anchors it (``document_id::order``), the same id scheme the evidence-builder uses.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from trustrag.extract.types import BlockKind, ExtractedBlock, ExtractedDoc, StructureType


class StructureNode(BaseModel):
    """One node of a document's structure, in a shape uniform across all types."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: str
    parent_id: str | None
    label: str
    # The node's role (e.g. "heading", "slide") — a free label, not a closed enum,
    # so new structure types add nodes without widening a shared type.
    kind: str
    # The Evidence Unit this node anchors, by eu_id (document_id::order).
    eu_ref: str


class StructureIndex(BaseModel):
    """The structure of one document: its type plus uniform-shape nodes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    structure_type: StructureType
    nodes: tuple[StructureNode, ...] = ()


def _eu_ref(doc: ExtractedDoc, block: ExtractedBlock) -> str:
    return f"{doc.document_id}::{block.order}"


def _heading_tree(doc: ExtractedDoc) -> tuple[StructureNode, ...]:
    """Nest heading blocks by their ``level``; no headings ⇒ zero nodes."""
    nodes: list[StructureNode] = []
    # Stack of (level, node_id) ancestors; pop until the top is a strict parent.
    stack: list[tuple[int, str]] = []
    for block in doc.blocks:
        if block.kind is not BlockKind.heading or not block.text.strip():
            continue
        level = block.level if block.level is not None else 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_id = stack[-1][1] if stack else None
        node_id = _eu_ref(doc, block)
        nodes.append(
            StructureNode(
                node_id=node_id,
                parent_id=parent_id,
                label=block.text,
                kind="heading",
                eu_ref=node_id,
            )
        )
        stack.append((level, node_id))
    return tuple(nodes)


def _slide_sequence(doc: ExtractedDoc) -> tuple[StructureNode, ...]:
    """One flat node per slide block, in document order."""
    nodes: list[StructureNode] = []
    for block in doc.blocks:
        if block.kind is not BlockKind.slide or not block.text.strip():
            continue
        node_id = _eu_ref(doc, block)
        nodes.append(
            StructureNode(
                node_id=node_id,
                parent_id=None,
                label=block.text,
                kind="slide",
                eu_ref=node_id,
            )
        )
    return tuple(nodes)


def build_structure(doc: ExtractedDoc) -> StructureIndex:
    """Build the best-effort Structure Index for ``doc`` (§7b).

    Dispatch is by ``doc.structure_type``: a ``heading_tree`` nests its heading
    blocks by level; a ``slide_sequence`` yields one node per slide in order. Every
    other type — including ``none`` and a heading document with no headings —
    degrades to **zero nodes**. The result is always a valid ``StructureIndex``;
    an empty one is a normal outcome, never an error.
    """
    if doc.structure_type is StructureType.heading_tree:
        nodes = _heading_tree(doc)
    elif doc.structure_type is StructureType.slide_sequence:
        nodes = _slide_sequence(doc)
    else:
        nodes = ()
    return StructureIndex(
        document_id=doc.document_id,
        structure_type=doc.structure_type,
        nodes=nodes,
    )
