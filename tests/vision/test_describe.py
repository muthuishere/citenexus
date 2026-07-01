"""`describe_image` orchestrates an injected `VisionPlugin` into an EU-ready record.

Hermetic: `FakeVision` is a deterministic in-process plugin (no network). Real
VL inference needs an injected endpoint; this layer only shapes the output.
"""

from trustrag.extract.types import ImageRef
from trustrag.plugins.base import VisionPlugin
from trustrag.vision import FakeVision, VisionRecord, describe_image


def test_fake_vision_is_a_vision_plugin() -> None:
    fake = FakeVision()
    assert isinstance(fake, VisionPlugin)
    assert fake.plugin_version  # non-empty version stamp (§4c)


def test_describe_image_returns_populated_record_without_network() -> None:
    img = ImageRef(image_id="fig-7", page=2, width=600, height=400)
    record = describe_image(img, FakeVision())

    assert isinstance(record, VisionRecord)
    assert record.image_id == "fig-7"
    assert record.short_caption
    assert record.detailed_description
    assert len(record.objects) > 0
    assert len(record.relationships) > 0
    assert record.ocr_text is not None


def test_describe_image_is_deterministic() -> None:
    img = ImageRef(image_id="fig-7", page=2, width=600, height=400)
    assert describe_image(img, FakeVision()) == describe_image(img, FakeVision())


def test_vision_record_is_frozen_and_forbids_extra() -> None:
    record = describe_image(ImageRef(image_id="fig-1", width=10, height=10), FakeVision())
    assert record.model_config["frozen"] is True
    assert record.model_config["extra"] == "forbid"
