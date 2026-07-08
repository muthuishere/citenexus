"""to_markdown — deterministic ExtractedDoc → GitHub-flavored markdown."""

from __future__ import annotations

from citenexus.extract.markdown import to_markdown
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
)


def _doc(*blocks: ExtractedBlock) -> ExtractedDoc:
    return ExtractedDoc(document_id="doc", source_type=SourceType.txt, blocks=blocks)


def _block(
    kind: BlockKind, text: str, page: int | None = None, level: int | None = None
) -> ExtractedBlock:
    return ExtractedBlock(order=0, kind=kind, text=text, page=page, level=level)


def test_heading_levels_render_and_clamp() -> None:
    doc = _doc(
        _block(BlockKind.heading, "Two", level=2),
        _block(BlockKind.heading, "Default"),
        _block(BlockKind.heading, "Nine", level=9),
    )
    assert to_markdown(doc) == "## Two\n\n# Default\n\n###### Nine\n"


def test_verbatim_kinds() -> None:
    doc = _doc(
        _block(BlockKind.paragraph, "A paragraph."),
        _block(BlockKind.table, "name: ada, age: 36"),
        _block(BlockKind.thread_turn, "reply text"),
        _block(BlockKind.ocr_block, "scanned words"),
    )
    assert to_markdown(doc) == (
        "A paragraph.\n\nname: ada, age: 36\n\nreply text\n\nscanned words\n"
    )


def test_code_is_fenced() -> None:
    doc = _doc(_block(BlockKind.code, "x = 1\ny = 2"))
    assert to_markdown(doc) == "```\nx = 1\ny = 2\n```\n"


def test_slide_heading_from_page() -> None:
    doc = _doc(
        _block(BlockKind.slide, "Title frame\nBody frame", page=1),
        _block(BlockKind.slide, "No page slide"),
    )
    assert to_markdown(doc) == ("## Slide 1\n\nTitle frame\nBody frame\n\nNo page slide\n")


def test_image_text_or_placeholder() -> None:
    doc = _doc(
        _block(BlockKind.image, "figure caption"),
        _block(BlockKind.image, ""),
    )
    assert to_markdown(doc) == "figure caption\n\n![image]()\n"


def test_empty_text_blocks_are_skipped() -> None:
    doc = _doc(
        _block(BlockKind.paragraph, "kept"),
        _block(BlockKind.paragraph, ""),
        _block(BlockKind.paragraph, "also kept"),
    )
    assert to_markdown(doc) == "kept\n\nalso kept\n"


def test_empty_document_renders_empty() -> None:
    assert to_markdown(_doc()) == ""


def _table_row(header: tuple[str, ...], cells: tuple[str, ...]) -> ExtractedBlock:
    return ExtractedBlock(
        order=0,
        kind=BlockKind.table,
        text="ignored verbatim text",
        structure_path=header,
        cells=cells,
    )


def test_contiguous_rows_fuse_into_one_gfm_table() -> None:
    doc = _doc(
        _table_row(("name", "age"), ("ada", "36")),
        _table_row(("name", "age"), ("lin", "29")),
    )
    assert to_markdown(doc) == "| name | age |\n| --- | --- |\n| ada | 36 |\n| lin | 29 |\n"


def test_different_headers_and_short_rows_split_and_pad() -> None:
    doc = _doc(
        _table_row(("a", "b"), ("1",)),  # short row → padded
        _table_row(("x",), ("9", "extra")),  # new header → new table; extra truncated
    )
    assert to_markdown(doc) == "| a | b |\n| --- | --- |\n| 1 |  |\n\n| x |\n| --- |\n| 9 |\n"


def test_pipes_and_newlines_in_cells_are_escaped() -> None:
    doc = _doc(_table_row(("h|x", "y"), ("a|b", "c\nd")))
    assert to_markdown(doc) == "| h\\|x | y |\n| --- | --- |\n| a\\|b | c d |\n"


def test_headerless_table_block_stays_verbatim() -> None:
    doc = _doc(_block(BlockKind.table, "name: ada, age: 36"))
    assert to_markdown(doc) == "name: ada, age: 36\n"


def test_rendering_is_deterministic() -> None:
    doc = _doc(
        _block(BlockKind.heading, "T", level=1),
        _block(BlockKind.paragraph, "body"),
    )
    assert to_markdown(doc) == to_markdown(doc)
