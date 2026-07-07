"""ExtractedDoc → GitHub-flavored markdown — pure, deterministic, total.

The behavior reference for the Rust twin (``rust/src/emit/markdown.rs``);
the parity suite proves both render byte-identical markdown. Rules:
heading → ``#`` repeated clamp(level or 1, 1, 6) times; paragraph/table/thread_turn/
ocr_block → text verbatim; code → fenced; slide → ``## Slide {page}`` +
text (heading omitted when ``page`` is unset); image → text, or the
``![image]()`` placeholder when empty. Blocks join with one blank line;
empty renderings are skipped; non-empty output ends with one newline.
"""

from __future__ import annotations

from citenexus.extract.types import BlockKind, ExtractedBlock, ExtractedDoc


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
    parts = [rendered for block in doc.blocks if (rendered := _render(block))]
    return "\n\n".join(parts) + "\n" if parts else ""
