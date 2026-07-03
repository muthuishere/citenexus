"""build_evidence_units — blocks → Evidence Units (spec §7)."""

import pytest

from citenexus.domain.partition import PartitionPath
from citenexus.evidence.builder import build_evidence_units
from citenexus.evidence.unit import EUType
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
    StructureType,
)


def _partition() -> PartitionPath:
    return PartitionPath.of(
        ("org", "acme"), ("product_line", "contracts"), ("product", "nda-review")
    )


def _doc(*blocks: ExtractedBlock, **kw: object) -> ExtractedDoc:
    defaults: dict[str, object] = {
        "document_id": "nda_2026",
        "source_type": SourceType.pdf,
        "source_uri": "s3://bucket/nda_2026.pdf",
        "blocks": blocks,
    }
    defaults.update(kw)
    return ExtractedDoc(**defaults)


def test_each_block_maps_to_one_evidence_unit() -> None:
    doc = _doc(
        ExtractedBlock(order=0, kind=BlockKind.paragraph, text="a"),
        ExtractedBlock(order=1, kind=BlockKind.paragraph, text="b"),
        ExtractedBlock(order=2, kind=BlockKind.paragraph, text="c"),
    )
    eus = build_evidence_units(doc, partition=_partition(), language="en")
    assert len(eus) == 3


@pytest.mark.parametrize(
    ("kind", "eu_type"),
    [
        (BlockKind.paragraph, EUType.paragraph),
        (BlockKind.heading, EUType.section),
        (BlockKind.table, EUType.table),
        (BlockKind.code, EUType.code_block),
        (BlockKind.image, EUType.image),
        (BlockKind.slide, EUType.page_summary),
        (BlockKind.thread_turn, EUType.paragraph),
        (BlockKind.ocr_block, EUType.ocr_block),
    ],
)
def test_block_kind_maps_to_eu_type(kind: BlockKind, eu_type: EUType) -> None:
    doc = _doc(ExtractedBlock(order=0, kind=kind, text="content"))
    (eu,) = build_evidence_units(doc, partition=_partition(), language="en")
    assert eu.type is eu_type


def test_eu_id_scheme_is_document_id_and_order() -> None:
    doc = _doc(
        ExtractedBlock(order=0, kind=BlockKind.paragraph, text="a"),
        ExtractedBlock(order=7, kind=BlockKind.paragraph, text="b"),
    )
    eus = build_evidence_units(doc, partition=_partition(), language="en")
    assert [eu.eu_id for eu in eus] == ["nda_2026::0", "nda_2026::7"]


def test_citation_carries_verbatim_passage_page_and_bbox() -> None:
    doc = _doc(
        ExtractedBlock(
            order=3,
            kind=BlockKind.paragraph,
            text="The employee shall not disclose confidential information.",
            page=12,
            bbox=(120.0, 300.0, 510.0, 380.0),
        ),
    )
    (eu,) = build_evidence_units(doc, partition=_partition(), language="en")
    assert eu.citation.passage == "The employee shall not disclose confidential information."
    assert eu.citation.page == 12
    assert eu.citation.bbox == (120.0, 300.0, 510.0, 380.0)
    assert eu.text == "The employee shall not disclose confidential information."
    assert eu.page == 12


def test_structure_path_is_carried() -> None:
    doc = _doc(
        ExtractedBlock(
            order=0,
            kind=BlockKind.paragraph,
            text="x",
            structure_path=("Agreement", "5. Confidentiality", "5.2"),
        ),
    )
    (eu,) = build_evidence_units(doc, partition=_partition(), language="en")
    assert eu.structure_path == ("Agreement", "5. Confidentiality", "5.2")


def test_acl_is_carried_opaque_and_unparsed() -> None:
    acl = {"roles": ["partner"], "matter": "m7"}
    doc = _doc(ExtractedBlock(order=0, kind=BlockKind.paragraph, text="x"))
    (eu,) = build_evidence_units(doc, partition=_partition(), language="en", acl=acl)
    # Same object, unmodified.
    assert eu.acl is acl


def test_acl_defaults_to_none() -> None:
    doc = _doc(ExtractedBlock(order=0, kind=BlockKind.paragraph, text="x"))
    (eu,) = build_evidence_units(doc, partition=_partition(), language="en")
    assert eu.acl is None


def test_empty_text_blocks_are_skipped() -> None:
    doc = _doc(
        ExtractedBlock(order=0, kind=BlockKind.paragraph, text="real"),
        ExtractedBlock(order=1, kind=BlockKind.paragraph, text=""),
        ExtractedBlock(order=2, kind=BlockKind.paragraph, text="   "),
        ExtractedBlock(order=3, kind=BlockKind.paragraph, text="also real"),
    )
    eus = build_evidence_units(doc, partition=_partition(), language="en")
    assert [eu.eu_id for eu in eus] == ["nda_2026::0", "nda_2026::3"]


def test_language_is_stamped() -> None:
    doc = _doc(ExtractedBlock(order=0, kind=BlockKind.paragraph, text="x"))
    (eu,) = build_evidence_units(doc, partition=_partition(), language="de")
    assert eu.language == "de"


def test_partition_and_source_uri_are_carried() -> None:
    part = _partition()
    doc = _doc(ExtractedBlock(order=0, kind=BlockKind.paragraph, text="x"))
    (eu,) = build_evidence_units(doc, partition=part, language="en")
    assert eu.partition == part
    assert eu.document_id == "nda_2026"
    assert eu.source_uri == "s3://bucket/nda_2026.pdf"


def test_empty_doc_yields_no_units() -> None:
    doc = _doc(structure_type=StructureType.none)
    assert build_evidence_units(doc, partition=_partition(), language="en") == []


def test_build_is_deterministic() -> None:
    doc = _doc(
        ExtractedBlock(order=0, kind=BlockKind.heading, text="H"),
        ExtractedBlock(order=1, kind=BlockKind.paragraph, text="p"),
    )
    a = build_evidence_units(doc, partition=_partition(), language="en")
    b = build_evidence_units(doc, partition=_partition(), language="en")
    assert a == b
