// Emit phase — the pure builder for a PendingVisionRequest (ADR-0005, §9).
//
// The deterministic heart of the two-phase seam: the exact request bytes — the
// data URI encoding, the prompt, the request_id format — are computed here and
// pinned as conformance/cases/vision_orchestration.json. Credential-free by
// construction: the payload the host POSTs carries the image and the prompt and
// nothing else.

/** A bounding box `[x0, y0, x1, y1]` in page coordinates.
 *  Mirrors `python/src/citenexus/domain/vision.py:26`. */
export type BBox = [number, number, number, number];

/** Where an emitted request's figure lives — the citation target the assembled
 *  figure Evidence Unit points back at. */
export interface VisionSourceRef {
  document: string;
  page: number | null;
  bbox: BBox | null;
  source_uri: string | null;
}

/** The model-ready content the host POSTs: the prompt plus the base64
 *  `image_url` data URI, both assembled by the core. Provider-shaped (OpenAI
 *  `image_url`) and credential-free — the host wraps it in its own request with
 *  its own model, temperature and auth. */
export interface VisionPayload {
  prompt: string;
  image_url: string;
}

/** One figure awaiting host fulfillment — the two-phase seam's unit of work.
 *  `request_id` is the figure's future `eu_id` (`{document}::img::{image_id}`)
 *  and the sole key a fulfilled description is addressed back by. */
export interface PendingVisionRequest {
  request_id: string;
  payload: VisionPayload;
  source_ref: VisionSourceRef;
}

/** Fallback when the bytes carry no recognized magic — matches the extractor's
 *  default so unrecognized blobs stay stable. */
const DEFAULT_SUBTYPE = "png";

function startsWith(data: Uint8Array, prefix: readonly number[]): boolean {
  if (data.length < prefix.length) return false;
  for (let i = 0; i < prefix.length; i++) if (data[i] !== prefix[i]) return false;
  return true;
}

const PNG_MAGIC = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
const JPEG_MAGIC = [0xff, 0xd8, 0xff];
const GIF87A = [0x47, 0x49, 0x46, 0x38, 0x37, 0x61];
const GIF89A = [0x47, 0x49, 0x46, 0x38, 0x39, 0x61];
const RIFF = [0x52, 0x49, 0x46, 0x46];
const WEBP = [0x57, 0x45, 0x42, 0x50];

/** Recognize the image type from its magic bytes → the `image/<subtype>`
 *  subtype (png/jpeg/gif/webp), or `null` if unrecognized. Byte-for-byte port of
 *  `python/src/citenexus/extract/mime.py:13`. */
export function sniffImageSubtype(data: Uint8Array): string | null {
  if (startsWith(data, PNG_MAGIC)) return "png";
  if (startsWith(data, JPEG_MAGIC)) return "jpeg";
  if (startsWith(data, GIF87A) || startsWith(data, GIF89A)) return "gif";
  if (data.length >= 12 && startsWith(data, RIFF) && startsWith(data.subarray(8, 12), WEBP)) {
    return "webp";
  }
  return null;
}

/** Base64-encode raw bytes without assuming Node's Buffer is present — this
 *  module must stay usable in a browser or a Cloudflare Worker. */
export function base64Encode(data: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < data.length; i++) binary += String.fromCharCode(data[i]!);
  // eslint-disable-next-line no-undef
  return btoa(binary);
}

/**
 * Encode image bytes as an OpenAI-shaped base64 `image_url` data URI.
 *
 * The core owns the payload, so it declares the image's TRUE format by sniffing
 * the magic bytes (§9) — a JPEG figure emits `data:image/jpeg` — so a port that
 * POSTs the pinned payload verbatim never mislabels the media type.
 */
export function imageDataUri(data: Uint8Array): string {
  const subtype = sniffImageSubtype(data) ?? DEFAULT_SUBTYPE;
  return `data:image/${subtype};base64,${base64Encode(data)}`;
}

/** The optional citation geometry of an emitted request. */
export interface BuildRequestOptions {
  page?: number | null;
  bbox?: BBox | null;
  sourceUri?: string | null;
}

/** Shape one image + its bytes into a model-ready, credential-free request.
 *  Port of `vision/requests.py:33`. */
export function buildPendingRequest(
  documentId: string,
  imageId: string,
  data: Uint8Array,
  prompt: string,
  options: BuildRequestOptions = {},
): PendingVisionRequest {
  return {
    request_id: `${documentId}::img::${imageId}`,
    payload: { prompt, image_url: imageDataUri(data) },
    source_ref: {
      document: documentId,
      page: options.page ?? null,
      bbox: options.bbox ?? null,
      source_uri: options.sourceUri ?? null,
    },
  };
}
