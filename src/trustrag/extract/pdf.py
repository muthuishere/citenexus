"""PdfExtractor — text per page with page numbers + word bboxes via pdfplumber (§8)."""

from __future__ import annotations

from typing import Any

import pdfplumber

from trustrag.evidence.unit import BBox
from trustrag.extract.plain import open_binary
from trustrag.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    ImageRef,
    SourceType,
    StructureType,
)
from trustrag.plugins.base import ExtractorPlugin


def _page_text_bbox(page: Any) -> BBox | None:
    """The bounding box covering every extracted word on the page, where feasible."""
    words = page.extract_words()
    if not words:
        return None
    x0 = min(float(w["x0"]) for w in words)
    top = min(float(w["top"]) for w in words)
    x1 = max(float(w["x1"]) for w in words)
    bottom = max(float(w["bottom"]) for w in words)
    return (x0, top, x1, bottom)


class PdfExtractor(ExtractorPlugin):
    """One paragraph block per page (text + page number + a word-derived bbox);
    page images become ``ImageRef``s anchored to their page and box."""

    plugin_version = "pdf/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        opened, doc_id, source_uri = open_binary(source, self.document_id)

        blocks: list[ExtractedBlock] = []
        images: list[ImageRef] = []
        with pdfplumber.open(opened) as pdf:
            for index, page in enumerate(pdf.pages):
                number = index + 1
                text = (page.extract_text() or "").strip()
                blocks.append(
                    ExtractedBlock(
                        order=index,
                        kind=BlockKind.paragraph,
                        text=text,
                        page=number,
                        bbox=_page_text_bbox(page),
                    )
                )
                for img_index, img in enumerate(page.images):
                    images.append(
                        ImageRef(
                            image_id=f"page{number}-img{img_index}",
                            page=number,
                            bbox=(
                                float(img["x0"]),
                                float(img["top"]),
                                float(img["x1"]),
                                float(img["bottom"]),
                            ),
                        )
                    )

        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.pdf,
            structure_type=StructureType.page_layout,
            source_uri=source_uri,
            blocks=tuple(blocks),
            images=tuple(images),
        )
