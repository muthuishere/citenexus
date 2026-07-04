"""Conditional-vision pre-filter — the §9 decision table as a pure function.

Vision is NOT a blanket stage. Sending every embedded image to a VL model is
slow, costly, and often wrong: a born-digital text page needs no vision at all,
a scanned-text raster is better served by OCR, and page decoration (rules,
banners, logos) carries no answerable content. So before any vision call the
pipeline asks `decide`: given one `ImageRef`, the area of its page, and whether
the region is OCR-dense, route it to exactly one of four outcomes.

The decision (§9):

- **text**  — text-native page: the page has an authoritative text layer and is
  not rasterized. Callers signal this with ``page_area=None``; the pre-filter
  short-circuits and the extracted text is used as-is. No image processing.
- **ocr**   — an embedded raster that is scanned text (OCR-dense). Cheaper and
  more faithful to OCR than to a VL model.
- **vision** — a meaningful figure: it clears the area/aspect guards and is not
  OCR-dense. This is the only outcome that spends a vision call.
- **skip**  — decoration: too small a share of the page (below ``min_area_ratio``)
  or a banner/strip aspect ratio outside the configured bounds.

Pure and deterministic: no I/O, no network, no plugin call — those happen only
after a region is routed to ``vision`` (see ``describe.py``).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from citenexus.extract.types import ImageRef


class VisionDecision(StrEnum):
    """The four routes an image can take through the §9 pre-filter."""

    text = "text"
    ocr = "ocr"
    vision = "vision"
    skip = "skip"


class VisionPrefilterConfig(BaseModel):
    """Operator-tunable thresholds for the §9 pre-filter.

    ``min_area_ratio`` is the smallest share of its page an image may cover and
    still be considered meaningful. ``skip_if_ocr_dense`` routes OCR-dense
    rasters to OCR rather than vision (set ``False`` to vision them anyway). The
    optional aspect-ratio bounds guard against banner/strip decoration; set
    either to ``None`` to disable that side of the check.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_area_ratio: float = 0.05
    skip_if_ocr_dense: bool = True
    min_aspect_ratio: float | None = 0.125
    max_aspect_ratio: float | None = 8.0


def decide(
    image: ImageRef,
    *,
    page_area: float | None,
    ocr_text_dense: bool,
    config: VisionPrefilterConfig,
) -> VisionDecision:
    """Route one image to text / ocr / vision / skip per the §9 table.

    ``page_area`` is the area of the image's page in the same units as the
    image's ``width * height``; pass ``None`` for a text-native page (the
    pre-filter then returns ``text``). ``ocr_text_dense`` is the extractor's
    signal that the region is scanned text.
    """
    # Pre-filter: text-native page → use the text layer; no image processing.
    if page_area is None:
        return VisionDecision.text

    width = image.width or 0
    height = image.height or 0
    image_area = float(width * height)
    area_ratio = image_area / page_area if page_area > 0 else 0.0

    # Decoration: too small a share of the page to carry answerable content.
    if area_ratio < config.min_area_ratio:
        return VisionDecision.skip

    # Decoration: banner/strip aspect ratios (very wide or very tall).
    if width > 0 and height > 0:
        aspect = width / height
        if config.max_aspect_ratio is not None and aspect > config.max_aspect_ratio:
            return VisionDecision.skip
        if config.min_aspect_ratio is not None and aspect < config.min_aspect_ratio:
            return VisionDecision.skip

    # Scanned-text raster: cheaper and more faithful to OCR than to a VL model.
    if ocr_text_dense and config.skip_if_ocr_dense:
        return VisionDecision.ocr

    # A meaningful figure: this is what vision is for.
    return VisionDecision.vision
