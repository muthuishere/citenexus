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


def test_anchor_with_href_renders_inline_markdown_link() -> None:
    doc = HtmlExtractor().extract('<p>go <a href="https://x.test">here</a></p>')
    assert doc.blocks[0].text == "go[here](https://x.test)"


def test_anchor_without_href_is_plain_text() -> None:
    doc = HtmlExtractor().extract("<p>plain <a>anchor</a> word</p>")
    assert doc.blocks[0].text == "plainanchorword"


def test_unordered_list_becomes_dash_lines() -> None:
    doc = HtmlExtractor().extract("<ul><li>alpha</li><li>beta</li></ul>")
    assert [b.kind for b in doc.blocks] == [BlockKind.paragraph]
    assert doc.blocks[0].text == "- alpha\n- beta"


def test_ordered_list_is_numbered_and_empty_items_dropped() -> None:
    doc = HtmlExtractor().extract("<ol><li>one</li><li></li><li>three</li></ol>")
    assert doc.blocks[0].text == "1. one\n2. three"


def test_list_items_carry_links_and_are_not_duplicated_as_paragraphs() -> None:
    doc = HtmlExtractor().extract(
        '<ul><li><p>wrapped <a href="/x">link</a></p></li></ul>'
    )
    # One block for the list; the <p> inside <li> is not emitted separately.
    assert [b.kind for b in doc.blocks] == [BlockKind.paragraph]
    assert doc.blocks[0].text == "- wrapped[link](/x)"
