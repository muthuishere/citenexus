"""Assemble phase — join fulfilled descriptions into cited figure EUs (§9).

`build_vision_units` is the third phase of the two-phase seam: given the emitted
`PendingVisionRequest`s and the host's ``{request_id: VisionRecord}``, it joins by
``request_id`` and builds figure Evidence Units. The text is the model's
description (searchable), the citation points at the request's ``source_ref``
(page + bbox), provenance stays honest — "this claim came from the figure at
page 4, described by a model", not verbatim source text.
"""

from __future__ import annotations

from citenexus.domain.partition import PartitionPath
from citenexus.domain.vision import BBox, PendingVisionRequest, VisionPayload, VisionSourceRef
from citenexus.evidence.unit import EUType
from citenexus.vision.describe import VisionRecord
from citenexus.vision.units import build_vision_units


def _partition() -> PartitionPath:
    return PartitionPath.of(("org", "acme"))


def _request(
    request_id: str, *, page: int | None = None, bbox: BBox | None = None
) -> PendingVisionRequest:
    return PendingVisionRequest(
        request_id=request_id,
        payload=VisionPayload(prompt="p", image_url="data:image/png;base64,QUJD"),
        source_ref=VisionSourceRef(document=request_id.split("::")[0], page=page, bbox=bbox),
    )


def test_description_becomes_eu_text_cited_to_image_region() -> None:
    request = _request("annual-report::img::page4-img0", page=4, bbox=(10.0, 20.0, 110.0, 220.0))
    record = VisionRecord(
        image_id=request.request_id,
        short_caption="Revenue chart",
        detailed_description="A line chart of revenue rising each quarter.",
        ocr_text="Q1 Q2 Q3 Q4",
    )
    units = build_vision_units(
        [request], {request.request_id: record}, partition=_partition(), language="en"
    )
    assert len(units) == 1
    eu = units[0]
    assert eu.type is EUType.figure
    assert eu.page == 4
    assert eu.citation.bbox == (10.0, 20.0, 110.0, 220.0)
    # the searchable text carries caption + description + any OCR'd text
    assert "Revenue chart" in eu.text
    assert "rising each quarter" in eu.text
    assert "Q1 Q2 Q3 Q4" in eu.text
    # eu_id is the request_id, namespaced so it never collides with block EUs
    assert eu.eu_id == "annual-report::img::page4-img0"


def test_empty_description_is_skipped() -> None:
    request = _request("d::img::x", page=1)
    record = VisionRecord(image_id=request.request_id, short_caption="", detailed_description="")
    units = build_vision_units(
        [request], {request.request_id: record}, partition=_partition(), language="en"
    )
    assert units == []
