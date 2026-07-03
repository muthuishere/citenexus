"""TxtExtractor — plain text split into blank-line-separated paragraphs (§8)."""

from __future__ import annotations

import re
from typing import Any

from citenexus.extract.plain import load_text
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
    StructureType,
)
from citenexus.plugins.base import ExtractorPlugin

_BLANK_LINE = re.compile(r"\n[ \t]*\n+")


class TxtExtractor(ExtractorPlugin):
    """A ``.txt`` source has no structure: each paragraph is one paragraph block."""

    plugin_version = "txt/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        text, doc_id, source_uri = load_text(source, self.document_id)
        chunks = [chunk.strip() for chunk in _BLANK_LINE.split(text)]
        blocks = tuple(
            ExtractedBlock(order=i, kind=BlockKind.paragraph, text=chunk)
            for i, chunk in enumerate(c for c in chunks if c)
        )
        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.txt,
            structure_type=StructureType.none,
            source_uri=source_uri,
            blocks=blocks,
        )
