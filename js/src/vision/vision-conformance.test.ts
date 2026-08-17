// The §9 two-phase vision vectors, asserted as a BINDING contract.
//
// `conformance/cases/vision_orchestration.json` is the cross-port contract for
// vision ORCHESTRATION — emit -> fulfil -> assemble, with only the raw model
// call in the middle per-host (ADR-0005). Vision is an injected model like the
// generator and the embedder, so everything around the call is deterministic and
// ports natively (ADR-0010 tier 1).
// This mirrors `python/tests/conformance/test_vision_orchestration_vectors.py`
// and `golang/vision/vision_conformance_test.go` case for case: the committed
// JSON is read as OPAQUE DATA, never re-derived by calling the code under test,
// and every count is pinned EXACTLY.

import { describe, expect, it } from "vitest";

import { loadCase, loadData } from "../conform/fixtures.js";
import { VISION_DESCRIBE_PROMPT } from "../gen/prompts.js";
import { recordFromMapping, type VisionRecord } from "./describe.js";
import { fulfillVisionRequests, type VisionFulfiller } from "./fulfill.js";
import { buildPendingRequest, type BBox, type PendingVisionRequest } from "./requests.js";
import { buildVisionUnits, type EvidenceUnit, type PartitionPath } from "./units.js";

interface VisionCase {
  document_id: string;
  source_uri: string;
  language: string;
  images: { image_id: string; bytes_b64: string }[];
  emit: PendingVisionRequest[];
  fulfilled: Record<string, VisionRecord>;
  assembled_eus: EvidenceUnit[];
  degrade: {
    fulfilled: Record<string, VisionRecord>;
    assembled_eu_ids: string[];
  };
}

const CASE = loadCase<VisionCase>("vision_orchestration.json");
const PROMPTS = loadData<Record<string, string>>("prompts.json");

/** Pinned EXACTLY. A vector silently dropped from the fixture is a weakened
 *  contract that no per-case assertion can see. */
const EXPECTED_IMAGES = 2;
const EXPECTED_EMITTED = 2;
const EXPECTED_FULFILLED = 2;
const EXPECTED_ASSEMBLED = 2;
const EXPECTED_DEGRADED_UNITS = 1;

const PARTITION: PartitionPath = CASE.assembled_eus[0]!.partition;

function decodeBase64(value: string): Uint8Array {
  // eslint-disable-next-line no-undef
  const binary = atob(value);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

/** Drive the fixture's IMAGES (not its expectations) through the real emit
 *  phase, taking the prompt from the port's own generated copy so a paraphrase
 *  fails here instead of quietly agreeing with itself. */
function emitFromFixture(): PendingVisionRequest[] {
  return CASE.images.map((image, index) => {
    const expected = CASE.emit[index]!;
    return buildPendingRequest(
      CASE.document_id,
      image.image_id,
      decodeBase64(image.bytes_b64),
      VISION_DESCRIBE_PROMPT,
      {
        page: expected.source_ref.page,
        bbox: expected.source_ref.bbox as BBox | null,
        sourceUri: CASE.source_uri,
      },
    );
  });
}

/** Replay the fixture's own responses in place of the model, keyed on the
 *  EMITTED image_url — a port that emitted a different data URI would not find
 *  its response here, which is what makes the substitution honest. */
function fixtureFulfiller(failing: ReadonlySet<string> = new Set()): VisionFulfiller {
  const byImageUrl = new Map<string, Record<string, unknown>>();
  for (const emitted of CASE.emit) {
    byImageUrl.set(
      emitted.payload.image_url,
      CASE.fulfilled[emitted.request_id] as unknown as Record<string, unknown>,
    );
  }
  return (imageUrl: string, prompt: string) => {
    if (failing.has(imageUrl)) throw new Error("vision endpoint failed for this image");
    expect(prompt, "the host must be handed the emitted prompt verbatim").toBe(
      VISION_DESCRIBE_PROMPT,
    );
    const mapping = byImageUrl.get(imageUrl);
    if (mapping === undefined) throw new Error(`no fixture response for ${imageUrl}`);
    return mapping;
  };
}

describe("vision orchestration conformance", () => {
  it("pins the vector counts exactly", () => {
    expect(CASE.images).toHaveLength(EXPECTED_IMAGES);
    expect(CASE.emit).toHaveLength(EXPECTED_EMITTED);
    expect(Object.keys(CASE.fulfilled)).toHaveLength(EXPECTED_FULFILLED);
    expect(CASE.assembled_eus).toHaveLength(EXPECTED_ASSEMBLED);
    expect(CASE.degrade.assembled_eu_ids).toHaveLength(EXPECTED_DEGRADED_UNITS);
  });

  it("ships the pinned prompt, in the generated copy and in every payload", () => {
    // The prompt rides in every payload the host POSTs verbatim, so a paraphrase
    // is a different model input — pinned as tier-2 shared data (ADR-0010).
    expect(VISION_DESCRIBE_PROMPT).toBe(PROMPTS["vision_describe"]);
    for (const emitted of CASE.emit) {
      expect(emitted.payload.prompt).toBe(PROMPTS["vision_describe"]);
    }
  });

  it("declares each image's TRUE media type, sniffed from the magic bytes", () => {
    // A port that hardcoded image/png passes the first vector and fails the second.
    const prefixes = emitFromFixture().map((r) => r.payload.image_url.split(";", 1)[0]);
    expect(prefixes).toEqual(["data:image/png", "data:image/jpeg"]);
  });

  it.each(CASE.emit.map((e, i) => [e.request_id, i] as const))(
    "emits %s byte-identically to the fixture",
    (_requestId, index) => {
      expect(emitFromFixture()[index]).toEqual(CASE.emit[index]);
    },
  );

  it("emits no credential — only image content and a prompt", () => {
    // The load-bearing ADR-0005 invariant.
    for (const request of emitFromFixture()) {
      expect(Object.keys(request.payload).sort()).toEqual(["image_url", "prompt"]);
    }
  });

  it.each(Object.keys(CASE.fulfilled))("shapes the record for %s", (requestId) => {
    const expected = CASE.fulfilled[requestId]!;
    expect(
      recordFromMapping(expected.image_id, expected as unknown as Record<string, unknown>),
    ).toEqual(expected);
  });

  it("joins every fulfilled response by request_id", async () => {
    const fulfilled = await fulfillVisionRequests(emitFromFixture(), fixtureFulfiller());
    expect(fulfilled).toEqual(CASE.fulfilled);
  });

  it("assembles the pinned figure evidence units", async () => {
    const requests = emitFromFixture();
    const fulfilled = await fulfillVisionRequests(requests, fixtureFulfiller());
    const units = buildVisionUnits(requests, fulfilled, {
      partition: PARTITION,
      language: CASE.language,
    });
    expect(units).toEqual(CASE.assembled_eus);
  });

  it("degrades when a model call fails, and never fabricates a caption", async () => {
    // The degrade path, driven end-to-end: the first image's model call FAILS.
    // Per-request isolation means the second image still produces its unit, and
    // the first produces none — not an empty caption, not a placeholder.
    const requests = emitFromFixture();
    const failing = new Set([requests[0]!.payload.image_url]);
    const fulfilled = await fulfillVisionRequests(requests, fixtureFulfiller(failing));
    expect(fulfilled).toEqual(CASE.degrade.fulfilled);

    const units = buildVisionUnits(requests, fulfilled, {
      partition: PARTITION,
      language: CASE.language,
    });
    expect(units.map((u) => u.eu_id)).toEqual(CASE.degrade.assembled_eu_ids);
    expect(units.map((u) => u.eu_id)).not.toContain(requests[0]!.request_id);
  });

  it("yields no unit for an empty description", async () => {
    // A model that returns junk (no caption, no description) must also degrade —
    // an EU whose text is empty is a citation to nothing.
    const requests = emitFromFixture();
    const fulfilled = await fulfillVisionRequests(requests, () => ({}));
    expect(Object.keys(fulfilled)).toHaveLength(EXPECTED_FULFILLED);
    expect(
      buildVisionUnits(requests, fulfilled, { partition: PARTITION, language: CASE.language }),
    ).toEqual([]);
  });
});
