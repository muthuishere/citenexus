"""MdExtractor — Markdown headings (level + structure_path) and paragraphs (§8)."""

from __future__ import annotations

from typing import Any

from markdown_it import MarkdownIt

from citenexus.extract.plain import load_text
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
    StructureType,
)
from citenexus.plugins.base import ExtractorPlugin


class MdExtractor(ExtractorPlugin):
    """Headings become heading blocks (with a level + ancestor structure_path);
    paragraphs become paragraph blocks tagged with the enclosing heading path."""

    plugin_version = "md/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        text, doc_id, source_uri = load_text(source, self.document_id)
        tokens = MarkdownIt().parse(text)

        blocks: list[ExtractedBlock] = []
        stack: list[tuple[int, str]] = []  # (level, heading text) ancestors
        order = 0
        has_heading = False

        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.type == "heading_open":
                level = int(tok.tag[1:])
                content = tokens[i + 1].content.strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                ancestors = tuple(t for _, t in stack)
                blocks.append(
                    ExtractedBlock(
                        order=order,
                        kind=BlockKind.heading,
                        text=content,
                        level=level,
                        structure_path=ancestors,
                    )
                )
                stack.append((level, content))
                has_heading = True
                order += 1
                i += 3
            elif tok.type == "paragraph_open":
                content = tokens[i + 1].content.strip()
                if content:
                    blocks.append(
                        ExtractedBlock(
                            order=order,
                            kind=BlockKind.paragraph,
                            text=content,
                            structure_path=tuple(t for _, t in stack),
                        )
                    )
                    order += 1
                i += 3
            elif tok.type in ("fence", "code_block"):
                # BlockKind.code / EUType.code_block are defined and mapped
                # (evidence/builder.py:_KIND_TO_TYPE) but no extractor ever
                # constructed one — a fenced (```lang) or 4-space-indented
                # code block is a single token (not an open/close pair), with
                # its literal source in .content (never HTML-escaped/inline
                # tokens like paragraph/heading text is).
                content = tok.content.rstrip("\n")
                if content:
                    blocks.append(
                        ExtractedBlock(
                            order=order,
                            kind=BlockKind.code,
                            text=content,
                            structure_path=tuple(t for _, t in stack),
                        )
                    )
                    order += 1
                i += 1
            else:
                i += 1

        structure = StructureType.heading_tree if has_heading else StructureType.none
        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.md,
            structure_type=structure,
            source_uri=source_uri,
            blocks=tuple(blocks),
        )
