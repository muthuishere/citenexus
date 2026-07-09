"""PdfExtractor — text per page with page numbers + word bboxes (§8).

The fixture ``fixtures/sample.pdf`` is a hermetic, hand-built single-page PDF
(one text line), so this stays a unit test — no network, no external tooling.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from citenexus.extract.pdf import PdfExtractor
from citenexus.extract.types import BlockKind, SourceType, StructureType
from tests.extract.fixtures.pdf_builder import build_pdf_with_image

SAMPLE_PDF = Path(__file__).parent / "fixtures" / "sample.pdf"


def test_extracts_text_with_page_number() -> None:
    doc = PdfExtractor().extract(SAMPLE_PDF)
    assert doc.source_type is SourceType.pdf
    assert doc.structure_type is StructureType.page_layout
    assert doc.document_id == "sample"
    assert len(doc.blocks) == 1
    block = doc.blocks[0]
    assert block.kind is BlockKind.paragraph
    assert block.page == 1
    assert "Hello PDF" in block.text
    # Word bboxes are feasible for this fixture → a page text bbox is set.
    assert block.bbox is not None
    assert len(block.bbox) == 4


def test_extracts_real_decodable_image_bytes() -> None:
    pdf_bytes = build_pdf_with_image()
    doc = PdfExtractor(document_id="withimg").extract(io.BytesIO(pdf_bytes))

    assert len(doc.images) == 1
    image = doc.images[0]
    assert image.page == 1
    assert image.bbox is not None
    # blob_key is stamped later by the ingest pipeline, not the extractor.
    assert image.blob_key is None

    data = doc.image_bytes[image.image_id]
    assert len(data) > 0
    # Must be real, Pillow-decodable image bytes — not raw/opaque stream data.
    decoded = Image.open(io.BytesIO(data))
    decoded.load()
    assert decoded.size[0] > 0 and decoded.size[1] > 0
