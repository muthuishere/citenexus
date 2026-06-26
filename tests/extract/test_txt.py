"""TxtExtractor — blank-line-separated paragraphs, no structure (§8)."""

from __future__ import annotations

from trustrag.extract.txt import TxtExtractor
from trustrag.extract.types import BlockKind, SourceType, StructureType


def test_paragraphs_split_on_blank_lines() -> None:
    doc = TxtExtractor().extract("First paragraph line.\n\nSecond paragraph here.")
    assert doc.source_type is SourceType.txt
    assert doc.structure_type is StructureType.none
    assert [b.kind for b in doc.blocks] == [BlockKind.paragraph, BlockKind.paragraph]
    assert [b.order for b in doc.blocks] == [0, 1]
    assert doc.blocks[0].text == "First paragraph line."
    assert doc.blocks[1].text == "Second paragraph here."


def test_document_id_from_filename(tmp_path: object) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    p = tmp_path / "notes.txt"
    p.write_text("hello", encoding="utf-8")
    doc = TxtExtractor().extract(p)
    assert doc.document_id == "notes"
    assert doc.source_uri == str(p)
