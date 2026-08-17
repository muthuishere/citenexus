// The §9 conditional-vision ORCHESTRATION — everything around the model call,
// none of the model call.
//
// Vision is an injected model, exactly like the generator and the embedder: the
// library hosts none of them. What it does own is deterministic and therefore
// portable by construction — the pre-filter that decides whether a model is
// called at all, the emitted request payload, the parse of the model's reply,
// and the assembly of citable figure Evidence Units. The model call itself is
// fulfilled by the HOST (ADR-0005 two-phase emit/fulfil), so no credential ever
// crosses into this module.
//
// Plain ESM, no native library (ADR-0010 tier 1). The pinned prompt is tier-2
// shared data, generated into `src/gen/prompts.ts` from conformance/prompts.json.
//
// This file owns the pre-filter: vision is NOT a blanket stage. Sending every
// embedded image to a VL model is slow, costly, and often wrong — a born-digital
// text page needs no vision, a scanned-text raster is better served by OCR, and
// page decoration carries no answerable content.

/** The four routes an image can take through the §9 pre-filter. Only "vision"
 *  spends a model call. */
export type VisionDecision = "text" | "ocr" | "vision" | "skip";

/** Operator-tunable §9 thresholds. Mirrors
 *  `python/src/citenexus/vision/prefilter.py:44` VisionPrefilterConfig; a `null`
 *  aspect bound disables that side of the check. */
export interface VisionPrefilterConfig {
  /** Smallest share of its page an image may cover and still be meaningful. */
  minAreaRatio: number;
  /** Route OCR-dense rasters to OCR rather than vision. */
  skipIfOcrDense: boolean;
  minAspectRatio: number | null;
  maxAspectRatio: number | null;
}

/** The reference defaults (0.05 / true / 0.125 / 8.0). */
export const DEFAULT_PREFILTER_CONFIG: VisionPrefilterConfig = {
  minAreaRatio: 0.05,
  skipIfOcrDense: true,
  minAspectRatio: 0.125,
  maxAspectRatio: 8.0,
};

/** A meaningful image asset — a candidate for conditional vision.
 *  Mirrors `python/src/citenexus/extract/types.py:62`. */
export interface ImageRef {
  image_id: string;
  page?: number | null;
  bbox?: BBox | null;
  width?: number | null;
  height?: number | null;
  /** Where the bytes live (a backend key), or null if not persisted yet. */
  blob_key?: string | null;
}

import type { BBox } from "./requests.js";

/**
 * Route one image to text / ocr / vision / skip per the §9 table.
 *
 * `pageArea` is the area of the image's page in the same units as the image's
 * width*height; pass `null` for a text-native page (the pre-filter then returns
 * "text"). `ocrTextDense` is the extractor's signal that the region is scanned
 * text. Pure: no I/O, no network, no model call.
 *
 * Byte-for-byte port of `vision/prefilter.py:62`, including the ORDER of the
 * guards — area before aspect before OCR-density — which is observable whenever
 * more than one would fire.
 */
export function decide(
  image: ImageRef,
  pageArea: number | null,
  ocrTextDense: boolean,
  config: VisionPrefilterConfig = DEFAULT_PREFILTER_CONFIG,
): VisionDecision {
  // Pre-filter: text-native page → use the text layer; no image processing.
  if (pageArea === null) return "text";

  const width = image.width ?? 0;
  const height = image.height ?? 0;
  const imageArea = width * height;
  const areaRatio = pageArea > 0 ? imageArea / pageArea : 0.0;

  // Decoration: too small a share of the page to carry answerable content.
  if (areaRatio < config.minAreaRatio) return "skip";

  // Decoration: banner/strip aspect ratios (very wide or very tall).
  if (width > 0 && height > 0) {
    const aspect = width / height;
    if (config.maxAspectRatio !== null && aspect > config.maxAspectRatio) return "skip";
    if (config.minAspectRatio !== null && aspect < config.minAspectRatio) return "skip";
  }

  // Scanned-text raster: cheaper and more faithful to OCR than to a VL model.
  if (ocrTextDense && config.skipIfOcrDense) return "ocr";

  // A meaningful figure: this is what vision is for.
  return "vision";
}
