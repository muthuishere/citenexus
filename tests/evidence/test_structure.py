"""build_structure — best-effort, source-type-aware Structure Index (spec §7b)."""

import pytest
from pydantic import ValidationError

from citenexus.evidence.structure import StructureIndex, StructureNode, build_structure
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
    StructureType,
)


def _doc(*blocks: ExtractedBlock, **kw: object) -> ExtractedDoc:
    defaults: dict[str, object] = {
        "document_id": "doc1",
        "source_type": SourceType.pdf,
        "blocks": blocks,
    }
    defaults.update(kw)
    return ExtractedDoc(**defaults)


def test_heading_tree_builds_nested_nodes_with_parent_links() -> None:
    doc = _doc(
        ExtractedBlock(order=0, kind=BlockKind.heading, text="Agreement", level=1),
        ExtractedBlock(order=1, kind=BlockKind.paragraph, text="intro"),
        ExtractedBlock(order=2, kind=BlockKind.heading, text="5. Confidentiality", level=2),
        ExtractedBlock(order=3, kind=BlockKind.heading, text="5.2 Exceptions", level=3),
        ExtractedBlock(order=4, kind=BlockKind.heading, text="6. Term", level=2),
        source_type=SourceType.docx,
        structure_type=StructureType.heading_tree,
    )
    index = build_structure(doc)
    assert index.structure_type is StructureType.heading_tree
    by_label = {n.label: n for n in index.nodes}
    # One node per heading block (paragraph is not a node).
    assert set(by_label) == {"Agreement", "5. Confidentiality", "5.2 Exceptions", "6. Term"}
    # Roots and parent links by heading level.
    assert by_label["Agreement"].parent_id is None
    assert by_label["5. Confidentiality"].parent_id == by_label["Agreement"].node_id
    assert by_label["5.2 Exceptions"].parent_id == by_label["5. Confidentiality"].node_id
    # Sibling at level 2 re-parents back up to the level-1 root, not the level-3 node.
    assert by_label["6. Term"].parent_id == by_label["Agreement"].node_id


def test_heading_node_links_to_its_evidence_unit() -> None:
    doc = _doc(
        ExtractedBlock(order=2, kind=BlockKind.heading, text="Confidentiality", level=1),
        structure_type=StructureType.heading_tree,
    )
    (node,) = build_structure(doc).nodes
    # eu_ref resolves to the heading block's Evidence Unit (document_id::order).
    assert node.eu_ref == "doc1::2"


def test_none_structure_yields_zero_nodes_without_error() -> None:
    doc = _doc(
        ExtractedBlock(order=0, kind=BlockKind.paragraph, text="a"),
        ExtractedBlock(order=1, kind=BlockKind.paragraph, text="b"),
        structure_type=StructureType.none,
    )
    index = build_structure(doc)
    assert isinstance(index, StructureIndex)
    assert index.nodes == ()
    assert index.structure_type is StructureType.none


def test_heading_tree_with_no_headings_yields_zero_nodes() -> None:
    doc = _doc(
        ExtractedBlock(order=0, kind=BlockKind.paragraph, text="flat text only"),
        structure_type=StructureType.heading_tree,
    )
    assert build_structure(doc).nodes == ()


def test_slide_sequence_one_node_per_slide_in_order() -> None:
    doc = _doc(
        ExtractedBlock(order=0, kind=BlockKind.slide, text="Title", level=0),
        ExtractedBlock(order=1, kind=BlockKind.slide, text="Agenda", level=1),
        ExtractedBlock(order=2, kind=BlockKind.slide, text="Summary", level=2),
        document_id="deck",
        source_type=SourceType.pptx,
        structure_type=StructureType.slide_sequence,
    )
    index = build_structure(doc)
    assert [n.label for n in index.nodes] == ["Title", "Agenda", "Summary"]
    assert [n.eu_ref for n in index.nodes] == ["deck::0", "deck::1", "deck::2"]
    # A slide sequence is flat — every slide is a top-level node.
    assert all(n.parent_id is None for n in index.nodes)


def test_node_shape_is_uniform_across_structure_types() -> None:
    heading_doc = _doc(
        ExtractedBlock(order=0, kind=BlockKind.heading, text="H", level=1),
        structure_type=StructureType.heading_tree,
    )
    slide_doc = _doc(
        ExtractedBlock(order=0, kind=BlockKind.slide, text="S"),
        structure_type=StructureType.slide_sequence,
    )
    fields = set(StructureNode.model_fields)
    assert fields == {"node_id", "parent_id", "label", "kind", "eu_ref"}
    for index in (build_structure(heading_doc), build_structure(slide_doc)):
        for node in index.nodes:
            assert set(node.model_dump()) == fields


def test_structure_index_is_frozen() -> None:
    index = build_structure(_doc(structure_type=StructureType.none))
    with pytest.raises(ValidationError):
        index.document_id = "other"  # type: ignore[misc]
