"""ExtractedDoc → GitHub-flavored markdown — pure, deterministic, total.

The behavior reference for the Rust twin (``rust/src/emit/markdown.rs``);
the parity suite proves both render byte-identical markdown. Rules:
heading → ``#`` repeated clamp(level or 1, 1, 6) times; paragraph/thread_turn/
ocr_block → text verbatim; code → fenced; slide → ``## Slide {page}`` +
text (heading omitted when ``page`` is unset); image → text, or the
``![image]()`` placeholder when empty. A run of contiguous ``table`` blocks
sharing a non-empty ``structure_path`` (their header) fuses into one
GitHub-flavored pipe table built from each block's ``cells``; a headerless
``table`` block falls back to its text verbatim. Blocks join with one blank
line; empty renderings are skipped; non-empty output ends with one newline.
"""

from __future__ import annotations

from citenexus.extract.types import BlockKind, ExtractedBlock, ExtractedDoc


def _escape_cell(text: str) -> str:
    """Pipe / newline are the two characters that would break a GFM table cell."""
    return text.replace("\n", " ").replace("|", "\\|")


def _render_table(header: tuple[str, ...], rows: list[ExtractedBlock]) -> str:
    """Render a run of table rows (all sharing ``header``) as one GFM pipe table."""
    ncols = len(header)
    lines = [
        "| " + " | ".join(_escape_cell(c) for c in header) + " |",
        "| " + " | ".join(["---"] * ncols) + " |",
    ]
    for block in rows:
        cells = [_escape_cell(c) for c in block.cells[:ncols]]
        cells += [""] * (ncols - len(cells))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _render(block: ExtractedBlock) -> str:
    if block.kind is BlockKind.heading:
        level = min(max(block.level or 1, 1), 6)
        return f"{'#' * level} {block.text}"
    if block.kind is BlockKind.code:
        return f"```\n{block.text}\n```" if block.text else ""
    if block.kind is BlockKind.slide:
        if block.page is None:
            return block.text
        heading = f"## Slide {block.page}"
        return f"{heading}\n\n{block.text}" if block.text else heading
    if block.kind is BlockKind.image:
        return block.text if block.text else "![image]()"
    # paragraph / table / thread_turn / ocr_block
    return block.text


def to_markdown(doc: ExtractedDoc) -> str:
    """Render ``doc``'s blocks, in document order, to markdown."""
    blocks = doc.blocks
    parts: list[str] = []
    i = 0
    n = len(blocks)
    while i < n:
        block = blocks[i]
        # Fuse a contiguous run of table rows sharing a header into one table.
        if block.kind is BlockKind.table and block.structure_path:
            header = block.structure_path
            run: list[ExtractedBlock] = []
            while (
                i < n
                and blocks[i].kind is BlockKind.table
                and blocks[i].structure_path == header
            ):
                run.append(blocks[i])
                i += 1
            parts.append(_render_table(header, run))
            continue
        rendered = _render(block)
        if rendered:
            parts.append(rendered)
        i += 1
    return "\n\n".join(parts) + "\n" if parts else ""
