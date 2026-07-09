"""HtmlExtractor — headings/paragraphs via bs4; scripts and styles stripped (§8)."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from citenexus.extract.plain import load_text
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
    StructureType,
)
from citenexus.plugins.base import ExtractorPlugin

_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def _li_own_text(li: Tag) -> str:
    """``li``'s own text, EXCLUDING any nested ``<ul>``/``<ol>`` subtree.

    A naive ``li.get_text()`` on a list item containing a nested list would
    duplicate the nested items' text (they're also captured as their own
    blocks by the same top-level ``find_all("li")`` walk) — only descend into
    non-list children.
    """
    parts: list[str] = []
    for child in li.children:
        if isinstance(child, Tag):
            if child.name in ("ul", "ol"):
                continue
            part = child.get_text(strip=True)
        else:
            part = str(child).strip()
        if part:
            parts.append(part)
    return " ".join(parts)


class HtmlExtractor(ExtractorPlugin):
    """Walk headings and paragraphs in document order; ``<script>``/``<style>``
    subtrees are removed before extraction so no markup or code leaks into text."""

    plugin_version = "html/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        text, doc_id, source_uri = load_text(source, self.document_id)
        soup = BeautifulSoup(text, "html.parser")
        for junk in soup(["script", "style"]):
            junk.decompose()

        blocks: list[ExtractedBlock] = []
        stack: list[tuple[int, str]] = []
        order = 0
        has_heading = False

        # <table> was previously outside the [*_HEADINGS, "p"] selector, so
        # its content was dropped entirely (not flattened, not cited). Pull
        # each table's rows out FIRST (each data row -> "col: value", same
        # convention as extract/csv.py -> its own BlockKind.table) and
        # decompose the <table> so its cell text can't also leak into a
        # paragraph block if a cell happens to nest a <p>.
        table_rows: list[tuple[tuple[str, ...], int, str]] = []
        captions: list[str] = []
        for table in soup.find_all("table"):
            caption_tag = table.find("caption")
            if caption_tag is not None:
                caption_text = caption_tag.get_text(strip=True)
                if caption_text:
                    captions.append(caption_text)
            rows = [
                [cell.get_text(strip=True) for cell in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")
            ]
            table.decompose()
            if len(rows) < 2:
                continue
            header = tuple(rows[0])
            for row_index, row in enumerate(rows[1:]):
                rendered = ", ".join(
                    f"{col}: {val}" for col, val in zip(header, row, strict=False)
                )
                table_rows.append((header, row_index, rendered))

        # <figcaption> (a figure's real caption text — distinct from a vision
        # model's own generated short_caption for an image, see row 5/row 6
        # of the coverage doc) was never selected either. Pull it out and
        # decompose it so it can't also leak into a surrounding paragraph.
        for figcaption in soup.find_all("figcaption"):
            caption_text = figcaption.get_text(strip=True)
            figcaption.decompose()
            if caption_text:
                captions.append(caption_text)

        # <pre> (a code block, conventionally <pre><code>...</code></pre>) was
        # never selected either — BlockKind.code/EUType.code_block are
        # defined and mapped but no extractor ever constructed one. Pull it
        # out FIRST and decompose it, same treatment as tables: preserves
        # internal whitespace/newlines (no strip=True) since code is
        # whitespace-significant, unlike prose.
        code_blocks: list[str] = []
        for pre in soup.find_all("pre"):
            content = pre.get_text().strip("\n")
            pre.decompose()
            if content:
                code_blocks.append(content)

        # <ul>/<ol>/<li> were previously outside the selector too — a list's
        # text was dropped entirely, not even flattened. Each <li> becomes
        # its own BlockKind.paragraph (no dedicated list EU type exists yet;
        # this matches how a DOCX "List Bullet" paragraph already reaches the
        # evidence store today — text survives, numbering/nesting does not).
        for el in soup.find_all([*_HEADINGS, "p", "li"]):
            if not isinstance(el, Tag):
                continue
            content = _li_own_text(el) if el.name == "li" else el.get_text(strip=True)
            if not content:
                continue
            if el.name in _HEADINGS:
                level = int(el.name[1:])
                while stack and stack[-1][0] >= level:
                    stack.pop()
                blocks.append(
                    ExtractedBlock(
                        order=order,
                        kind=BlockKind.heading,
                        text=content,
                        level=level,
                        structure_path=tuple(t for _, t in stack),
                    )
                )
                stack.append((level, content))
                has_heading = True
            else:
                blocks.append(
                    ExtractedBlock(
                        order=order,
                        kind=BlockKind.paragraph,
                        text=content,
                        structure_path=tuple(t for _, t in stack),
                    )
                )
            order += 1

        for header, row_index, rendered in table_rows:
            blocks.append(
                ExtractedBlock(
                    order=order,
                    kind=BlockKind.table,
                    text=rendered,
                    level=row_index,
                    structure_path=header,
                )
            )
            order += 1

        for content in code_blocks:
            blocks.append(ExtractedBlock(order=order, kind=BlockKind.code, text=content))
            order += 1

        for caption_text in captions:
            blocks.append(ExtractedBlock(order=order, kind=BlockKind.paragraph, text=caption_text))
            order += 1

        structure = StructureType.heading_tree if has_heading else StructureType.none
        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.html,
            structure_type=structure,
            source_uri=source_uri,
            blocks=tuple(blocks),
        )
