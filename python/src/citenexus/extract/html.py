"""HtmlExtractor — headings/paragraphs/lists/tables/code/captions via bs4;
scripts and styles stripped; ``<a href>`` rendered inline as ``[text](href)``
(§8).

The behavior reference for the Rust twin (``rust/src/extract/html.rs``) is
``_rich_text``/list rendering; both emit byte-identical ``ExtractedDoc`` JSON
for headings/paragraphs/lists/links. With no links or lists this reduces to
the original headings-and-paragraphs concatenation.
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from citenexus.evidence.unit import DocumentMetadata
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


def _html_metadata(soup: Any) -> DocumentMetadata:
    """``<title>`` and ``<meta name="author">`` — HTML has no standard
    created-date or page-count concept, so those stay ``None``."""
    title = soup.title.get_text(strip=True) if soup.title else None
    author_tag = soup.find("meta", attrs={"name": "author"})
    author = author_tag.get("content") if author_tag is not None else None
    return DocumentMetadata(title=title or None, author=author or None)


def _rich_text(el: Tag) -> str:
    """Every descendant text node stripped and concatenated (no separator),
    nothing under ``<script>``/``<style>``, and each ``<a href>`` rendered as
    ``[inner](href)`` without descending further — the bs4 twin of Rust's
    ``rich_text``."""
    parts: list[str] = []
    for child in el.children:
        # `type(...) is NavigableString` excludes Comment/CData/Doctype (which
        # subclass it) so only real text nodes are collected, matching Rust.
        if type(child) is NavigableString:
            trimmed = child.strip()
            if trimmed:
                parts.append(trimmed)
        elif isinstance(child, Tag):
            if child.name in ("script", "style"):
                continue
            if child.name == "a":
                href = child.get("href")
                if href is not None:
                    inner = _rich_text(child)
                    if inner:
                        parts.append(f"[{inner}]({href})")
                    continue
            parts.append(_rich_text(child))
    return "".join(parts)


def _inside_list(el: Tag) -> bool:
    """True when ``el`` sits inside a list (``ul``/``ol``/``li``)."""
    return el.find_parent(["ul", "ol", "li"]) is not None


def _render_list(list_el: Tag) -> str | None:
    """Render a ``ul``/``ol`` from its direct ``<li>`` children, or ``None``
    when it has no non-empty items."""
    ordered = list_el.name == "ol"
    lines: list[str] = []
    for li in list_el.find_all("li", recursive=False):
        if not isinstance(li, Tag):
            continue
        item = _rich_text(li)
        if not item:
            continue
        if ordered:
            lines.append(f"{len(lines) + 1}. {item}")
        else:
            lines.append(f"- {item}")
    return "\n".join(lines) if lines else None


class HtmlExtractor(ExtractorPlugin):
    """Walk headings, paragraphs, lists, tables, code blocks and captions in
    document order; ``<script>``/``<style>`` subtrees are removed first so no
    markup or code leaks into text; ``<a href>`` links survive as inline
    markdown."""

    plugin_version = "html/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        text, doc_id, source_uri = load_text(source, self.document_id)
        soup = BeautifulSoup(text, "html.parser")
        metadata = _html_metadata(soup)
        for junk in soup(["script", "style"]):
            junk.decompose()

        blocks: list[ExtractedBlock] = []
        stack: list[tuple[int, str]] = []
        order = 0
        has_heading = False

        # <table> was previously outside the selector, so its content was
        # dropped entirely (not flattened, not cited). Pull each table's
        # rows out FIRST (each data row -> "col: value", same convention as
        # extract/csv.py -> its own BlockKind.table) and decompose the
        # <table> so its cell text can't also leak into a paragraph block if
        # a cell happens to nest a <p>. A <caption> is captured too.
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
        # model's own generated short_caption for an image) was never
        # selected either. Pull it out and decompose it so it can't also
        # leak into a surrounding paragraph.
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

        for el in soup.find_all([*_HEADINGS, "p", "ul", "ol"]):
            if not isinstance(el, Tag):
                continue
            # Elements inside a list are rendered by their enclosing list block.
            if _inside_list(el):
                continue
            structure_path = tuple(t for _, t in stack)

            if el.name in ("ul", "ol"):
                list_text = _render_list(el)
                if list_text is not None:
                    blocks.append(
                        ExtractedBlock(
                            order=order,
                            kind=BlockKind.paragraph,
                            text=list_text,
                            structure_path=structure_path,
                        )
                    )
                    order += 1
                continue

            content = _rich_text(el)
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
                        structure_path=structure_path,
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
                        structure_path=structure_path,
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
            metadata=metadata,
            blocks=tuple(blocks),
        )
