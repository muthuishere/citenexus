"""PdfExtractor — text per page with page numbers + word bboxes via pdfplumber (§8)."""

from __future__ import annotations

import io
from typing import Any, cast

import pdfplumber
from PIL import Image, UnidentifiedImageError

from citenexus.evidence.unit import BBox
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


def _image_data(img: Any) -> bytes | None:
    """Decode one ``page.images`` entry's raw raster bytes, or ``None`` if unusable.

    ``pdfplumber``/``pdfminer`` expose the undecoded raster via the ``stream``
    key's ``.get_data()``. Not every embedded stream is a valid standalone
    image (some filters need page-level context to interpret) — validated by
    a real Pillow decode so a bad image is skipped rather than breaking the
    whole page.
    """
    stream = img.get("stream")
    if stream is None:
        return None
    try:
        data = cast("bytes", stream.get_data())
    except Exception:
        return None
    if not data:
        return None
    try:
        Image.open(io.BytesIO(data)).load()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    return data


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
        image_bytes: dict[str, bytes] = {}
        image_page_area: dict[str, float] = {}
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
                page_area = float(page.width) * float(page.height)
                for img_index, img in enumerate(page.images):
                    image_id = f"page{number}-img{img_index}"
                    x0, top, x1, bottom = (
                        float(img["x0"]),
                        float(img["top"]),
                        float(img["x1"]),
                        float(img["bottom"]),
                    )
                    images.append(
                        ImageRef(
                            image_id=image_id,
                            page=number,
                            bbox=(x0, top, x1, bottom),
                            width=round(x1 - x0),
                            height=round(bottom - top),
                        )
                    )
                    image_page_area[image_id] = page_area
                    data = _image_data(img)
                    if data is not None:
                        image_bytes[image_id] = data

        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.pdf,
            structure_type=StructureType.page_layout,
            source_uri=source_uri,
            blocks=tuple(blocks),
            images=tuple(images),
            image_bytes=image_bytes,
            image_page_area=image_page_area,
        )
