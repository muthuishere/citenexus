"""HtmlExtractor — headings/paragraphs/lists via bs4; scripts and styles
stripped; ``<a href>`` rendered inline as ``[text](href)`` (§8).

The behavior reference for the Rust twin (``rust/src/extract/html.rs``); both
emit byte-identical ``ExtractedDoc`` JSON. With no links or lists this reduces
to the original headings-and-paragraphs concatenation.
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

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
    """Walk headings, paragraphs and lists in document order; ``<script>`` /
    ``<style>`` subtrees are removed first so no markup or code leaks into
    text; ``<a href>`` links survive as inline markdown."""

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

        for el in soup.find_all([*_HEADINGS, "p", "ul", "ol"]):
            if not isinstance(el, Tag):
                continue
            # Elements inside a list are rendered by their enclosing list block.
            if _inside_list(el):
                continue
            structure_path = tuple(t for _, t in stack)

            if el.name in ("ul", "ol"):
                rendered = _render_list(el)
                if rendered is not None:
                    blocks.append(
                        ExtractedBlock(
                            order=order,
                            kind=BlockKind.paragraph,
                            text=rendered,
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

        structure = StructureType.heading_tree if has_heading else StructureType.none
        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.html,
            structure_type=structure,
            source_uri=source_uri,
            blocks=tuple(blocks),
        )
