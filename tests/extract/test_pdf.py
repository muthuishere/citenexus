"""PdfExtractor — text per page with page numbers + word bboxes (§8).

The fixture ``fixtures/sample.pdf`` is a hermetic, hand-built single-page PDF
(one text line), so this stays a unit test — no network, no external tooling.
"""

from __future__ import annotations

from pathlib import Path

from trustrag.extract.pdf import PdfExtractor
from trustrag.extract.types import BlockKind, SourceType, StructureType

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
