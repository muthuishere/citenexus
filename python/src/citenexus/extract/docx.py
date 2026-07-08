"""DocxExtractor — paragraphs + heading styles → heading_tree; images → ImageRef (§8)."""

from __future__ import annotations

from typing import Any

from docx import Document

from citenexus.extract.plain import open_binary
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    ImageRef,
    SourceType,
    StructureType,
)
from citenexus.plugins.base import ExtractorPlugin


def _heading_level(style_name: str) -> int | None:
    """A Word heading style (``Heading 1`` … ``Heading 9``) → its numeric level."""
    if not style_name.startswith("Heading"):
        return None
    tail = style_name[len("Heading") :].strip()
    return int(tail) if tail.isdigit() else 1


class DocxExtractor(ExtractorPlugin):
    """Heading-styled paragraphs build a heading tree; body paragraphs carry the
    enclosing heading path; embedded image parts become ``ImageRef``s."""

    plugin_version = "docx/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        opened, doc_id, source_uri = open_binary(source, self.document_id)
        document = Document(opened)

        blocks: list[ExtractedBlock] = []
        stack: list[tuple[int, str]] = []
        order = 0

        for para in document.paragraphs:
            content = para.text.strip()
            if not content:
                continue
            style_name = para.style.name if para.style is not None else None
            level = _heading_level(style_name or "")
            if level is not None:
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

        images: list[ImageRef] = []
        image_bytes: dict[str, bytes] = {}
        for rel_id, rel in document.part.rels.items():
            if "image" not in rel.reltype:
                continue
            images.append(ImageRef(image_id=rel_id))
            blob = getattr(rel.target_part, "blob", None)
            if blob:
                image_bytes[rel_id] = blob

        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.docx,
            structure_type=StructureType.heading_tree,
            source_uri=source_uri,
            blocks=tuple(blocks),
            images=tuple(images),
            image_bytes=image_bytes,
        )
