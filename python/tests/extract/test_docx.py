"""DocxExtractor — heading_tree from styles, images → ImageRef (§8)."""

from __future__ import annotations

import io

from PIL import Image

from citenexus.extract.docx import DocxExtractor
from citenexus.extract.types import BlockKind, SourceType, StructureType


def test_headings_paragraphs_and_image(docx_bytes: bytes) -> None:
    doc = DocxExtractor(document_id="memo").extract(io.BytesIO(docx_bytes))
    assert doc.source_type is SourceType.docx
    assert doc.structure_type is StructureType.heading_tree
    assert doc.document_id == "memo"

    kinds = [b.kind for b in doc.blocks]
    assert kinds == [
        BlockKind.heading,
        BlockKind.paragraph,
        BlockKind.heading,
        BlockKind.paragraph,
    ]
    h1, p1, h2, p2 = doc.blocks
    assert h1.text == "Title One"
    assert h1.level == 1
    assert h2.text == "Sub Section"
    assert h2.level == 2
    assert p1.text == "Body para under one."
    assert h2.structure_path == ("Title One",)
    assert p2.structure_path == ("Title One", "Sub Section")

    assert len(doc.images) == 1
    assert doc.images[0].image_id
    assert doc.images[0].blob_key is None  # stamped by the ingest pipeline, not here

    data = doc.image_bytes[doc.images[0].image_id]
    assert len(data) > 0
    decoded = Image.open(io.BytesIO(data))
    decoded.load()
