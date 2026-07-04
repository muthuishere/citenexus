import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import {
  claim,
  Decision,
  evidenceSignals,
  provenanceEntry,
  result,
  sourceRef,
  TrustMode,
  type Result,
} from "./result.js";

// The Result serialization is proven against the shared fixture — every case must
// round-trip byte-for-byte (parsed) against the Python reference. Follows the
// tokenize exemplar: load conformance/cases/result_roundtrip.json, assert over
// ALL cases, no leniency.
const NDA_TEXT = "The employee shall not disclose confidential information.";
const REFUSAL = "I can't answer that from the available evidence.";

const BUILDERS: Record<string, () => Result> = {
  "answered with full provenance": () =>
    result({
      answer: NDA_TEXT,
      answerLanguage: "en",
      mode: TrustMode.strict,
      evidence: evidenceSignals({
        decision: Decision.answered,
        supportingSources: 1,
        distinctDocuments: 1,
        allClaimsVerified: true,
        languagesInEvidence: ["en"],
      }),
      claims: [claim({ claim: NDA_TEXT, supported: true, sources: ["nda::0"] })],
      sources: [
        sourceRef({
          document: "nda",
          passage: NDA_TEXT,
          passageLanguage: "en",
          sourceUri: "raw/workspace=default/nda-sha",
        }),
      ],
      provenance: [
        provenanceEntry({
          claim: NDA_TEXT,
          evidenceUnit: "nda::0",
          documentId: "nda",
          s3Object: "raw/workspace=default/nda-sha",
          checksum: "a".repeat(64),
          producedBy: { embedding: "fake-hashing" },
        }),
      ],
    }),
  "refused on no evidence": () =>
    result({
      answer: REFUSAL,
      answerLanguage: "en",
      mode: TrustMode.strict,
      evidence: evidenceSignals({ decision: Decision.refused }),
      missingEvidence: ["no sufficiently relevant evidence found"],
    }),
};

interface RoundtripCase {
  name: string;
  result: unknown;
}

describe("result roundtrip conformance", () => {
  const cases = loadCase<RoundtripCase[]>("result_roundtrip.json");

  it("has cases", () => {
    expect(cases.length).toBeGreaterThan(0);
  });

  for (const c of cases) {
    it(`serializes ${JSON.stringify(c.name)}`, () => {
      const builder = BUILDERS[c.name];
      expect(builder, `no builder for case ${c.name}`).toBeDefined();
      const built = builder!();
      const serialized = JSON.parse(JSON.stringify(built));
      expect(serialized).toEqual(c.result);
    });
  }
});
