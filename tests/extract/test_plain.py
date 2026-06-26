"""PlainExtractor — raw str/bytes → a single paragraph; the unknown fallback (§8)."""

from __future__ import annotations

from trustrag.extract.plain import PlainExtractor
from trustrag.extract.types import BlockKind, SourceType, StructureType


def test_raw_string_becomes_one_paragraph() -> None:
    doc = PlainExtractor().extract("just some text")
    assert doc.source_type is SourceType.plain
    assert doc.structure_type is StructureType.none
    assert len(doc.blocks) == 1
    assert doc.blocks[0].kind is BlockKind.paragraph
    assert doc.blocks[0].order == 0
    assert doc.blocks[0].text == "just some text"


def test_bytes_input_is_decoded() -> None:
    doc = PlainExtractor().extract("café".encode())
    assert doc.blocks[0].text == "café"


def test_passed_document_id_is_used() -> None:
    doc = PlainExtractor(document_id="doc-42").extract("body")
    assert doc.document_id == "doc-42"
