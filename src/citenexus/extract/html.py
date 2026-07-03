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

        for el in soup.find_all([*_HEADINGS, "p"]):
            if not isinstance(el, Tag):
                continue
            content = el.get_text(strip=True)
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

        structure = StructureType.heading_tree if has_heading else StructureType.none
        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.html,
            structure_type=structure,
            source_uri=source_uri,
            blocks=tuple(blocks),
        )
