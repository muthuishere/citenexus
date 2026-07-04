"""Turn described document images into cited Evidence Units (§9).

A figure that clears the §9 pre-filter and is described by the vision plugin
becomes a first-class Evidence Unit so it is retrievable in context with the
surrounding text. The unit's ``text`` is the model's description (caption +
detail + any OCR'd text); its ``Citation`` points at the real image region
(page + bbox) — navigate the description, cite the figure. The ``eu_id`` is
namespaced ``{document_id}::img::{image_id}`` so it never collides with the
block units (``{document_id}::{order}``).

Pure and deterministic: the vision *call* happens upstream (``describe_image``);
this only shapes ``(ImageRef, VisionRecord)`` pairs into units.
"""

from __future__ import annotations

from typing import Any

from citenexus.domain.partition import PartitionPath
from citenexus.evidence.unit import Citation, EUType, EvidenceUnit
from citenexus.extract.types import ImageRef
from citenexus.vision.describe import VisionRecord


def _record_text(record: VisionRecord) -> str:
    """Compose the searchable text from a vision record's fields."""
    parts = [record.short_caption, record.detailed_description]
    if record.objects:
        parts.append(", ".join(record.objects))
    if record.relationships:
        parts.append("; ".join(record.relationships))
    if record.ocr_text:
        parts.append(record.ocr_text)
    return "\n".join(part for part in parts if part and part.strip()).strip()


def build_vision_units(
    described: list[tuple[ImageRef, VisionRecord]],
    *,
    document_id: str,
    partition: PartitionPath,
    language: str,
    acl: Any = None,
    source_uri: str | None = None,
) -> list[EvidenceUnit]:
    """Shape described images into figure Evidence Units; skip empty descriptions."""
    units: list[EvidenceUnit] = []
    for image, record in described:
        text = _record_text(record)
        if not text:
            continue
        units.append(
            EvidenceUnit(
                eu_id=f"{document_id}::img::{image.image_id}",
                partition=partition,
                document_id=document_id,
                type=EUType.figure,
                language=language,
                text=text,
                citation=Citation(passage=text, page=image.page, bbox=image.bbox),
                page=image.page,
                source_uri=source_uri,
                acl=acl,
            )
        )
    return units
