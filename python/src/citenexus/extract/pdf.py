"""PdfExtractor — text per page with page numbers + word bboxes via pdfplumber (§8)."""

from __future__ import annotations

import io
from typing import Any, cast

import pdfplumber
from PIL import Image, UnidentifiedImageError

from citenexus.evidence.unit import BBox, DocumentMetadata
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


def _pdf_metadata(pdf: Any) -> DocumentMetadata:
    """Real ``/Info`` dictionary values — title/author/created — plus page
    count. Every field is best-effort: absence in the source PDF is not an
    extraction failure."""
    info = pdf.metadata or {}
    return DocumentMetadata(
        title=info.get("Title") or None,
        author=info.get("Author") or None,
        created=info.get("CreationDate") or None,
        page_count=len(pdf.pages),
    )


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


def _text_excluding_tables(page: Any, tables: list[Any]) -> Any:
    """``page``, with every detected table's region cropped out.

    Without this, a table's cell text is captured TWICE: once as its own typed
    ``BlockKind.table`` row (see ``_extract_tables``) and again inside the raw
    page paragraph text — which both dilutes the paragraph EU and lets it tie
    a table row on retrieval score for the exact fact the table row exists to
    answer. Mirrors how an embedded image never leaks into paragraph text.
    """
    filtered = page
    for table in tables:
        filtered = filtered.outside_bbox(table.bbox)
    return filtered


def _extract_tables(
    tables: list[Any], page_number: int, start_order: int
) -> tuple[list[ExtractedBlock], int]:
    """Real ruled/aligned tables (already located via ``page.find_tables()``)
    -> one ``BlockKind.table`` block per data row (first row is the header,
    carried as ``structure_path``) — the same ``"col: value"`` rendering
    ``extract/csv.py`` uses, so a table row from a PDF cites identically to
    one from a CSV. Returns the new blocks and the next free ``order`` value
    (``ExtractedBlock.order`` must stay globally unique — it feeds ``eu_id``
    downstream).
    """
    blocks: list[ExtractedBlock] = []
    order = start_order
    for table in tables:
        rows = table.extract()
        if len(rows) < 2:
            continue
        header = tuple(cell or "" for cell in rows[0])
        bbox = cast("BBox", tuple(float(v) for v in table.bbox))
        for row_index, row in enumerate(rows[1:]):
            rendered = ", ".join(
                f"{col}: {val or ''}" for col, val in zip(header, row, strict=False)
            )
            blocks.append(
                ExtractedBlock(
                    order=order,
                    kind=BlockKind.table,
                    text=rendered,
                    page=page_number,
                    bbox=bbox,
                    level=row_index,
                    structure_path=header,
                )
            )
            order += 1
    return blocks, order


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
        order = 0
        with pdfplumber.open(opened) as pdf:
            metadata = _pdf_metadata(pdf)
            for index, page in enumerate(pdf.pages):
                number = index + 1
                tables = page.find_tables()
                text_page = _text_excluding_tables(page, tables) if tables else page
                text = (text_page.extract_text() or "").strip()
                blocks.append(
                    ExtractedBlock(
                        order=order,
                        kind=BlockKind.paragraph,
                        text=text,
                        page=number,
                        bbox=_page_text_bbox(text_page),
                    )
                )
                order += 1
                table_blocks, order = _extract_tables(tables, number, order)
                blocks.extend(table_blocks)
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
            metadata=metadata,
            blocks=tuple(blocks),
            images=tuple(images),
            image_bytes=image_bytes,
            image_page_area=image_page_area,
        )
