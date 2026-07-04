"""HtmlExtractor — headings/paragraphs; scripts and styles stripped (§8)."""

from __future__ import annotations

from citenexus.extract.html import HtmlExtractor
from citenexus.extract.types import BlockKind, SourceType, StructureType

HTML = (
    "<html><head><style>p{color:red}</style></head><body>"
    "<h1>Main</h1><p>Para one</p>"
    "<script>alert('bad')</script>"
    "<h2>Sub</h2><p>Para two</p>"
    "</body></html>"
)


def test_headings_paragraphs_and_strip() -> None:
    doc = HtmlExtractor().extract(HTML)
    assert doc.source_type is SourceType.html
    assert doc.structure_type is StructureType.heading_tree
    assert [b.kind for b in doc.blocks] == [
        BlockKind.heading,
        BlockKind.paragraph,
        BlockKind.heading,
        BlockKind.paragraph,
    ]
    main, p1, sub, p2 = doc.blocks
    assert main.text == "Main"
    assert main.level == 1
    assert p1.text == "Para one"
    assert sub.text == "Sub"
    assert sub.level == 2
    assert sub.structure_path == ("Main",)
    assert p2.structure_path == ("Main", "Sub")
    # No script/style content leaked anywhere.
    blob = " ".join(b.text for b in doc.blocks)
    assert "bad" not in blob
    assert "color" not in blob


def test_html_without_headings_has_no_structure() -> None:
    doc = HtmlExtractor().extract("<p>only a paragraph</p>")
    assert doc.structure_type is StructureType.none
    assert [b.kind for b in doc.blocks] == [BlockKind.paragraph]
