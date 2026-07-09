"""Shape an injected `VisionPlugin`'s output into an EU-ready vision record (§9).

Honest scope: real visual-language inference needs an injected endpoint — this
module owns no model. It only *orchestrates*: it takes an `ImageRef` already
routed to ``vision`` by the pre-filter, calls the operator-supplied
`VisionPlugin`, and normalizes the loosely-typed result into a `VisionRecord`
the evidence-builder can turn into a figure/diagram Evidence Unit.

`FakeVision` is a deterministic in-process plugin so the orchestration and
record-shaping are provable offline, with no network (the project's test rule).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from citenexus.extract.types import ImageRef
from citenexus.plugins.base import VisionPlugin


class VisionRecord(BaseModel):
    """A vision description shaped for an Evidence Unit (§7/§9).

    Carries the `ImageRef.image_id` it describes plus the fields a figure EU
    needs: a one-line caption, a fuller description, detected objects, their
    relationships, and any text the model read out of the image.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    image_id: str
    short_caption: str
    detailed_description: str = ""
    objects: tuple[str, ...] = ()
    relationships: tuple[str, ...] = ()
    ocr_text: str | None = None
    # Numeric/tabular values read off a chart, graph, or table-as-image.
    data_values: tuple[dict[str, Any], ...] = ()
    # photo | chart | diagram | screenshot | table | handwriting | logo | other.
    image_type: str | None = None


def _as_mapping(result: Any) -> Mapping[str, Any]:
    """Coerce a plugin result into a mapping, or fail loudly.

    The `VisionPlugin` contract is loosely typed (`describe` returns `Any`); a
    conforming plugin returns a mapping of the record fields. Anything else is a
    plugin bug, surfaced here rather than silently producing an empty record.
    """
    if isinstance(result, Mapping):
        return result
    raise TypeError(
        f"VisionPlugin.describe must return a mapping of record fields, got {type(result).__name__}"
    )


def describe_image(image: ImageRef, plugin: VisionPlugin) -> VisionRecord:
    """Call the injected vision plugin and shape its output into a `VisionRecord`."""
    data = _as_mapping(plugin.describe(image))
    return VisionRecord(
        image_id=image.image_id,
        short_caption=str(data.get("short_caption", "")),
        detailed_description=str(data.get("detailed_description", "")),
        objects=tuple(data.get("objects") or ()),
        relationships=tuple(data.get("relationships") or ()),
        ocr_text=data.get("ocr_text"),
        data_values=tuple(data.get("data_values") or ()),
        image_type=data.get("image_type"),
    )


class FakeVision(VisionPlugin):
    """A deterministic, network-free `VisionPlugin` for tests and the example.

    Derives every field from the image's id so output is reproducible. It stands
    in for an injected VL endpoint; it does not perform real inference.
    """

    plugin_version = "fake-vision-0"

    def describe(self, image_region: Any) -> dict[str, Any]:
        image_id = getattr(image_region, "image_id", str(image_region))
        return {
            "short_caption": f"Figure {image_id}",
            "detailed_description": (
                f"A deterministic description of figure {image_id} for offline tests."
            ),
            "objects": ("axis", "line", "legend"),
            "relationships": ("the line trends upward along the axis",),
            "ocr_text": f"label: {image_id}",
        }
