"""Assemble phase — join fulfilled descriptions into cited figure EUs (§9).

The third phase of the two-phase vision seam (ADR-0005): the core emitted
`PendingVisionRequest`s, the host fulfilled them into ``{request_id: VisionRecord}``,
and this joins the two by ``request_id`` to build the figure Evidence Units. Each
unit's ``text`` is the model's description (so it's retrievable in context); its
``Citation`` points at the real image region carried on the request's
``source_ref`` (page + bbox) — navigate the description, cite the figure. The
``eu_id`` is the request's ``request_id`` (``{document}::img::{image_id}``), so it
never collides with block units (``{document}::{order}``).

Per-request isolation and degrade-to-text live here: a request with no fulfilled
description, or an empty one, yields no unit and never fails the rest — identical
to the "no vision plugin" path. Pure and deterministic: the vision *call* happened
host-side; this only shapes descriptions into units.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from citenexus.domain.partition import PartitionPath
from citenexus.domain.vision import PendingVisionRequest
from citenexus.evidence.unit import Citation, EUType, EvidenceUnit
from citenexus.vision.describe import VisionRecord


def _record_text(record: VisionRecord) -> str:
    """Compose the searchable text from a vision record's fields."""
    parts = [record.short_caption, record.detailed_description]
    if record.image_type:
        parts.append(f"image type: {record.image_type}")
    if record.objects:
        parts.append(", ".join(record.objects))
    if record.relationships:
        parts.append("; ".join(record.relationships))
    if record.ocr_text:
        parts.append(record.ocr_text)
    if record.data_values:
        parts.append(
            "; ".join(f"{dv.get('label')}: {dv.get('value')}" for dv in record.data_values)
        )
    return "\n".join(part for part in parts if part and part.strip()).strip()


def build_vision_units(
    requests: Sequence[PendingVisionRequest],
    fulfilled: Mapping[str, VisionRecord],
    *,
    partition: PartitionPath,
    language: str,
    acl: Any = None,
) -> list[EvidenceUnit]:
    """Assemble figure Evidence Units by joining requests to fulfilled records.

    Joins on ``request_id``: a request the host did not fulfill (absent from
    ``fulfilled``), or whose description is empty, yields no unit and does not
    fail the others — per-request degrade-to-text.
    """
    units: list[EvidenceUnit] = []
    for request in requests:
        record = fulfilled.get(request.request_id)
        if record is None:
            continue
        text = _record_text(record)
        if not text:
            continue
        ref = request.source_ref
        units.append(
            EvidenceUnit(
                eu_id=request.request_id,
                partition=partition,
                document_id=ref.document,
                type=EUType.figure,
                language=language,
                text=text,
                citation=Citation(passage=text, page=ref.page, bbox=ref.bbox),
                page=ref.page,
                source_uri=ref.source_uri,
                acl=acl,
            )
        )
    return units
