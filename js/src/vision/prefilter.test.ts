// The §9 vision decision table as fixtures — one scenario per row, mirroring
// `python/tests/vision/test_prefilter.py` case for case. The pre-filter has no
// conformance vector of its own (`conformance/cases/vision_orchestration.json`
// pins emit/fulfil/assemble only), so these rows ARE the parity check: they are
// the reference's own inputs and the reference's own verdicts, copied as data.

import { describe, expect, it } from "vitest";

import {
  DEFAULT_PREFILTER_CONFIG,
  decide,
  type ImageRef,
  type VisionDecision,
  type VisionPrefilterConfig,
} from "./prefilter.js";

function imageOf(imageId: string, width: number, height: number): ImageRef {
  return { image_id: imageId, page: 1, width, height };
}

const NO_OCR_SKIP: VisionPrefilterConfig = { ...DEFAULT_PREFILTER_CONFIG, skipIfOcrDense: false };

describe("§9 vision pre-filter", () => {
  it("defaults match the reference", () => {
    expect(DEFAULT_PREFILTER_CONFIG.minAreaRatio).toBe(0.05);
    expect(DEFAULT_PREFILTER_CONFIG.skipIfOcrDense).toBe(true);
    expect(DEFAULT_PREFILTER_CONFIG.minAspectRatio).not.toBeNull();
    expect(DEFAULT_PREFILTER_CONFIG.maxAspectRatio).not.toBeNull();
  });

  const rows: [string, ImageRef, number | null, boolean, VisionPrefilterConfig, VisionDecision][] =
    [
      // A text-native page has an authoritative text layer (no rasterized page):
      // callers signal it with a null page area, and the pre-filter
      // short-circuits before any image work at all.
      [
        "text-native page routes to text",
        imageOf("img-text", 400, 300),
        null,
        false,
        DEFAULT_PREFILTER_CONFIG,
        "text",
      ],
      // An embedded raster that is scanned text → OCR, not a VL model.
      [
        "ocr-dense raster routes to ocr",
        imageOf("img-scan", 900, 900),
        1_000_000.0,
        true,
        DEFAULT_PREFILTER_CONFIG,
        "ocr",
      ],
      // Clears area and aspect, is not OCR-dense: the only row that spends a call.
      [
        "meaningful figure routes to vision",
        imageOf("img-fig", 600, 400),
        1_000_000.0,
        false,
        DEFAULT_PREFILTER_CONFIG,
        "vision",
      ],
      // area_ratio = 0.0064 < 0.05.
      [
        "tiny decoration below the area ratio skips",
        imageOf("img-deco", 80, 80),
        1_000_000.0,
        false,
        DEFAULT_PREFILTER_CONFIG,
        "skip",
      ],
      // area_ratio = 0.05 clears the area guard; aspect = 20 does not.
      [
        "banner aspect skips",
        imageOf("img-banner", 2000, 100),
        4_000_000.0,
        false,
        DEFAULT_PREFILTER_CONFIG,
        "skip",
      ],
      // The toggle is honored: with it off, an OCR-dense but meaningful image is
      // sent to vision instead of OCR.
      [
        "skipIfOcrDense=false routes meaningful to vision",
        imageOf("img-scan", 900, 900),
        1_000_000.0,
        true,
        NO_OCR_SKIP,
        "vision",
      ],
    ];

  it.each(rows)("%s", (_name, image, pageArea, ocrDense, config, want) => {
    expect(decide(image, pageArea, ocrDense, config)).toBe(want);
  });

  it("treats a zero page area as ratio 0, not a divide-by-zero", () => {
    // pageArea === 0 yields ratio 0.0 in the reference (prefilter.py:83), which
    // falls below minAreaRatio — skip, not NaN.
    expect(decide(imageOf("img", 100, 100), 0, false, DEFAULT_PREFILTER_CONFIG)).toBe("skip");
  });
});
