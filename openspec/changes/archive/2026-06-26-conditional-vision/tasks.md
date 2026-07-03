## 1. Tests first (red)

- [x] 1.1 `tests/vision/test_prefilter.py`: one scenario per §9 row —
      text-native (`page_area=None`) → text; OCR-dense raster → ocr; meaningful
      figure → vision; tiny decoration below `min_area_ratio` → skip; banner
      aspect → skip; `skip_if_ocr_dense=False` routes meaningful OCR-dense →
      vision; config defaults.
- [x] 1.2 `tests/vision/test_describe.py`: `describe_image` with `FakeVision`
      returns a populated `VisionRecord` (no network); `FakeVision` is a
      `VisionPlugin` with a non-empty `plugin_version`; record is deterministic,
      frozen, and extra-forbidding.

## 2. Implement (green)

- [x] 2.1 `src/citenexus/vision/prefilter.py`: `VisionDecision` StrEnum
      (text/ocr/vision/skip); frozen `VisionPrefilterConfig`
      (`min_area_ratio=0.05`, `skip_if_ocr_dense=True`, optional aspect bounds);
      pure `decide(image, *, page_area, ocr_text_dense, config)` per §9.
- [x] 2.2 `src/citenexus/vision/describe.py`: frozen EU-ready `VisionRecord`;
      thin `describe_image(image, plugin)` that shapes the injected plugin's
      result; deterministic, network-free `FakeVision(VisionPlugin)`.
- [x] 2.3 `src/citenexus/vision/__init__.py`: export `VisionDecision`,
      `VisionPrefilterConfig`, `decide`, `VisionRecord`, `describe_image`,
      `FakeVision`.

## 3. Verify

- [x] 3.1 `uv run pytest tests/vision -q` green.
- [x] 3.2 `uv run ruff check src/citenexus/vision tests/vision` clean.
- [x] 3.3 `uv run mypy src/citenexus/vision tests/vision` clean (strict).
- [x] 3.4 `npx -y @fission-ai/openspec@latest validate conditional-vision --strict`
      reports valid.
