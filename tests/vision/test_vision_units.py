"""build_vision_units — turn described images into cited Evidence Units (§9).

A figure that earns a vision call becomes a first-class Evidence Unit: its text
is the model's description (so it's searchable in context), but its citation
points at the real image region (page + bbox), and provenance marks it
vision-derived — honest for legal/medical ("this claim came from the figure at
page 4, described by a model", not verbatim source text).
"""

from __future__ import annotations

from trustrag.domain.partition import PartitionPath
from trustrag.evidence.unit import EUType
from trustrag.extract.types import ImageRef
from trustrag.vision.describe import VisionRecord
from trustrag.vision.units import build_vision_units


def _partition() -> PartitionPath:
    return PartitionPath.of(("org", "acme"))


def test_description_becomes_eu_text_cited_to_image_region() -> None:
    image = ImageRef(image_id="page4-img0", page=4, bbox=(10.0, 20.0, 110.0, 220.0))
    record = VisionRecord(
        image_id="page4-img0",
        short_caption="Revenue chart",
        detailed_description="A line chart of revenue rising each quarter.",
        ocr_text="Q1 Q2 Q3 Q4",
    )
    units = build_vision_units(
        [(image, record)],
        document_id="annual-report",
        partition=_partition(),
        language="en",
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
    # eu_id is namespaced so it never collides with block EUs (doc::N)
    assert eu.eu_id == "annual-report::img::page4-img0"


def test_empty_description_is_skipped() -> None:
    image = ImageRef(image_id="x", page=1)
    record = VisionRecord(image_id="x", short_caption="", detailed_description="")
    units = build_vision_units(
        [(image, record)], document_id="d", partition=_partition(), language="en"
    )
    assert units == []
