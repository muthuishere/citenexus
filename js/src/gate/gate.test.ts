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

describe("gate conformance", () => {
  const fixture = loadCase<Faithful>("faithful.json");

  it("has cases", () => {
    expect(fixture.supported.length).toBeGreaterThan(0);
    expect(fixture.relevance.length).toBeGreaterThan(0);
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
