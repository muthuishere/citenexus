"""The §9 vision decision table as fixtures — one scenario per row.

`decide` is pure: given an `ImageRef`, the page area, and whether the region is
OCR-dense, it routes to one of `text` / `ocr` / `vision` / `skip` (§9). Each
test below is one row of that table.
"""

from trustrag.extract.types import ImageRef
from trustrag.vision import VisionDecision, VisionPrefilterConfig, decide


def _image(image_id: str, *, width: int | None, height: int | None) -> ImageRef:
    return ImageRef(image_id=image_id, page=1, width=width, height=height)


def test_config_defaults() -> None:
    cfg = VisionPrefilterConfig()
    assert cfg.min_area_ratio == 0.05
    assert cfg.skip_if_ocr_dense is True
    # Optional aspect bounds default to sensible banner/strip guards.
    assert cfg.min_aspect_ratio is not None
    assert cfg.max_aspect_ratio is not None


def test_text_native_page_routes_to_text() -> None:
    # A text-native page has an authoritative text layer (no rasterized page):
    # callers signal it with page_area=None. The pre-filter short-circuits to text.
    img = _image("img-text", width=400, height=300)
    assert (
        decide(img, page_area=None, ocr_text_dense=False, config=VisionPrefilterConfig())
        is VisionDecision.text
    )


def test_ocr_dense_raster_routes_to_ocr() -> None:
    # An embedded raster that is scanned text → OCR, not a VL model.
    img = _image("img-scan", width=900, height=900)  # area_ratio = 0.81
    assert (
        decide(img, page_area=1_000_000.0, ocr_text_dense=True, config=VisionPrefilterConfig())
        is VisionDecision.ocr
    )


def test_meaningful_figure_routes_to_vision() -> None:
    # A meaningful figure that passes area/aspect and is not OCR-dense → vision.
    img = _image("img-fig", width=600, height=400)  # area_ratio = 0.24
    assert (
        decide(img, page_area=1_000_000.0, ocr_text_dense=False, config=VisionPrefilterConfig())
        is VisionDecision.vision
    )


def test_tiny_decoration_below_area_ratio_skips() -> None:
    # Decoration: a tiny image well below min_area_ratio → skip.
    img = _image("img-deco", width=80, height=80)  # area_ratio = 0.0064 < 0.05
    assert (
        decide(img, page_area=1_000_000.0, ocr_text_dense=False, config=VisionPrefilterConfig())
        is VisionDecision.skip
    )


def test_banner_aspect_skips() -> None:
    # Decoration: a wide banner strip whose area clears min_area_ratio but whose
    # aspect ratio is far outside the bounds → skip.
    img = _image("img-banner", width=2000, height=100)  # area_ratio = 0.05, aspect = 20
    assert (
        decide(img, page_area=4_000_000.0, ocr_text_dense=False, config=VisionPrefilterConfig())
        is VisionDecision.skip
    )


def test_skip_if_ocr_dense_false_routes_meaningful_to_vision() -> None:
    # The skip_if_ocr_dense toggle is honored: with it off, an OCR-dense but
    # meaningful image is sent to vision instead of OCR.
    cfg = VisionPrefilterConfig(skip_if_ocr_dense=False)
    img = _image("img-scan", width=900, height=900)
    assert (
        decide(img, page_area=1_000_000.0, ocr_text_dense=True, config=cfg) is VisionDecision.vision
    )
