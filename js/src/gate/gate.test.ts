import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import { hasRelevanceOverlap, isSupported } from "./gate.js";

// The gate is proven against the shared fixture — every case must match the
// Python reference (citenexus.answer.verify) exactly. Follows the tokenize
// exemplar: load conformance/cases/faithful.json, assert over ALL cases, no
// leniency.
interface Faithful {
  supported: { answer: string; passage: string; supported: boolean }[];
  relevance: { query: string; passage: string; relevant: boolean }[];
}

/** Bucket sizes, pinned. A vector silently dropped from a bucket is a weakened
 *  contract that no per-case assertion can see. */
const EXPECTED_COUNTS: Record<string, number> = { supported: 7, relevance: 5 };

describe("gate conformance", () => {
  const fixture = loadCase<Faithful>("faithful.json");

  it("bucket names and sizes are pinned", () => {
    const sizes = Object.fromEntries(
      Object.entries(fixture).map(([k, v]) => [k, (v as unknown[]).length]),
    );
    expect(sizes).toEqual(EXPECTED_COUNTS);
  });

  for (const c of fixture.supported) {
    it(`isSupported(${JSON.stringify(c.answer)}, ${JSON.stringify(c.passage)})`, () => {
      expect(isSupported(c.answer, c.passage)).toBe(c.supported);
    });
  }

  for (const c of fixture.relevance) {
    it(`hasRelevanceOverlap(${JSON.stringify(c.query)}, ${JSON.stringify(c.passage)})`, () => {
      expect(hasRelevanceOverlap(c.query, c.passage)).toBe(c.relevant);
    });
  }
});
