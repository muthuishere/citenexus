"""MdExtractor — headings (level + structure_path) and paragraphs (§8)."""

from __future__ import annotations

from citenexus.extract.md import MdExtractor
from citenexus.extract.types import BlockKind, SourceType, StructureType


def test_headings_and_paragraphs() -> None:
    src = "# Title\n\nIntro paragraph.\n\n## Section A\n\nBody of A.\n"
    doc = MdExtractor().extract(src)
    assert doc.source_type is SourceType.md
    assert doc.structure_type is StructureType.heading_tree
    kinds = [b.kind for b in doc.blocks]
    assert kinds == [
        BlockKind.heading,
        BlockKind.paragraph,
        BlockKind.heading,
        BlockKind.paragraph,
    ]
    assert [b.order for b in doc.blocks] == [0, 1, 2, 3]

    title, intro, section, body = doc.blocks
    assert title.text == "Title"
    assert title.level == 1
    assert title.structure_path == ()
    assert intro.text == "Intro paragraph."
    assert intro.structure_path == ("Title",)
    assert section.text == "Section A"
    assert section.level == 2
    assert section.structure_path == ("Title",)
    assert body.structure_path == ("Title", "Section A")


def test_plain_markdown_has_no_structure() -> None:
    doc = MdExtractor().extract("just a line of prose")
    assert doc.structure_type is StructureType.none
    assert [b.kind for b in doc.blocks] == [BlockKind.paragraph]
