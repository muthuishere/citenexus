"""PptxExtractor — one block per slide → slide_sequence, pictures → ImageRef (§8)."""

from __future__ import annotations

import io

from citenexus.extract.pptx import PptxExtractor
from citenexus.extract.types import BlockKind, SourceType, StructureType


def test_one_block_per_slide_and_picture(pptx_bytes: bytes) -> None:
    doc = PptxExtractor(document_id="deck").extract(io.BytesIO(pptx_bytes))
    assert doc.source_type is SourceType.pptx
    assert doc.structure_type is StructureType.slide_sequence
    assert [b.kind for b in doc.blocks] == [BlockKind.slide, BlockKind.slide]
    assert [b.order for b in doc.blocks] == [0, 1]
    assert [b.page for b in doc.blocks] == [1, 2]
    assert "Slide one body" in doc.blocks[0].text
    assert "Slide two body" in doc.blocks[1].text

    assert len(doc.images) == 1
    assert doc.images[0].page == 1
