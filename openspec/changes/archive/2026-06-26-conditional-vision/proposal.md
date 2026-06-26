## Why

Sending every embedded image to a visual-language model is slow, costly, and
often wrong: a born-digital text page needs no vision at all, a scanned-text
raster is better served by OCR, and page decoration (rules, banners, logos)
carries no answerable content. §9 makes vision **conditional** — a pure
pre-filter routes each image to the cheapest correct path before any model is
touched, and only earned figures spend a vision call.

## What Changes

- Add a **`VisionPrefilterConfig`** (frozen): `min_area_ratio=0.05`,
  `skip_if_ocr_dense=True`, and optional aspect-ratio bounds that guard against
  banner/strip decoration.
- Add a **`VisionDecision`** StrEnum — `text` / `ocr` / `vision` / `skip` — and a
  pure **`decide(image, *, page_area, ocr_text_dense, config)`** implementing the
  §9 table: text-native page → `text`; OCR-dense raster → `ocr`; meaningful
  figure → `vision`; decoration (tiny area-ratio or banner aspect) → `skip`.
- Add a **`VisionRecord`** (frozen, EU-ready: `short_caption`,
  `detailed_description`, `objects`, `relationships`, `ocr_text`) and a thin
  **`describe_image(image, plugin)`** that calls the injected `VisionPlugin` and
  shapes its loosely-typed result into that record.
- Add a deterministic **`FakeVision(VisionPlugin)`** so the orchestration and
  record-shaping are provable offline with no network.

No model is bundled — real VL inference needs the injected `VisionPlugin`
endpoint; this change owns only the pre-filter and the orchestration around it.

## Capabilities

### New Capabilities
- `conditional-vision`: a pure §9 pre-filter (`decide` → text/ocr/vision/skip)
  plus orchestration that shapes an injected `VisionPlugin`'s output into an
  EU-ready `VisionRecord`, with a deterministic test fake.

### Modified Capabilities
<!-- none -->

## Impact

- New module `src/trustrag/vision/`: `prefilter.py`, `describe.py`, `__init__.py`.
- Consumes `trustrag.extract.types.ImageRef` (input; unchanged) and the
  `VisionPlugin` seam from `trustrag.plugins.base` (unchanged).
- Downstream: ingestion (L3) routes extracted `ImageRef`s through `decide`, and
  the evidence-builder turns each `VisionRecord` into a figure/diagram Evidence
  Unit (§7). No dependency or API changes elsewhere; pillow already present.
