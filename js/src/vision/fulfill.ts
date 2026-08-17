// Fulfil phase — the host makes the model call (ADR-0005, §9).
//
// The two-phase seam has the HOST make every model call. This module emits
// credential-free PendingVisionRequests; a Fulfiller — `OpenAIVision` in
// production, a closure in tests — POSTs each payload with its own transport,
// auth and concurrency and hands back the parsed reply. Two invariants live
// here:
//
//   - Credential containment: the fulfiller only ever sees a
//     PendingVisionRequest (image content, no key); the key stays inside the
//     client's transport.
//   - Per-request isolation: a request whose fulfillment FAILS is dropped from
//     the result — degrade-to-text — never failing the ones that succeeded, and
//     never fabricating a caption to stand in for the missing one.

import { recordFromMapping, type VisionRecord } from "./describe.js";
import type { PendingVisionRequest } from "./requests.js";

/** The host-side seam, deliberately the thin "POST payload → return the parsed
 *  reply" shape ADR-0005 prescribes for a non-Python port. May be sync or async,
 *  matching `models.Transport`. */
export type VisionFulfiller = (
  imageUrl: string,
  prompt: string,
) => Record<string, unknown> | Promise<Record<string, unknown>>;

/** Parse the image's own id back out of a request_id
 *  (`{document}::img::{image_id}`); the assemble join keys on request_id. */
export function imageIdOf(requestId: string): string {
  const index = requestId.lastIndexOf("::img::");
  return index >= 0 ? requestId.slice(index + "::img::".length) : requestId;
}

/**
 * Run each pending request through `fulfill` and join the results by request_id.
 *
 * The emitted payload is handed over VERBATIM (no re-encode), so the host POSTs
 * exactly what this module emitted and every port reproduces the same bytes. A
 * request whose fulfillment THROWS or rejects — or yields no mapping — is
 * SKIPPED, so one failing image never fails the ingest of the rest and never
 * yields an invented description. Port of `vision/fulfill.py:56`.
 */
export async function fulfillVisionRequests(
  requests: readonly PendingVisionRequest[],
  fulfill: VisionFulfiller,
): Promise<Record<string, VisionRecord>> {
  const fulfilled: Record<string, VisionRecord> = {};
  for (const request of requests) {
    let mapping: Record<string, unknown>;
    try {
      mapping = await fulfill(request.payload.image_url, request.payload.prompt);
    } catch {
      continue;
    }
    if (mapping === null || mapping === undefined) continue;
    fulfilled[request.request_id] = recordFromMapping(imageIdOf(request.request_id), mapping);
  }
  return fulfilled;
}
