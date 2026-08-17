import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import { rrfFuse } from "./rrf.js";

// RRF is proven against the shared fixture — every case must match the Python
// reference exactly. Follows the tokenize exemplar: load
// conformance/cases/rrf.json, assert deep equality over ALL cases, no leniency.
/** Vector counts, pinned. A vector silently dropped from the fixture is a
 *  weakened contract that no per-case assertion can see. */
const EXPECTED_COUNTS: Record<string, number> = { cases: 5 };

describe("rrf conformance", () => {
  const cases = loadCase<{ lists: string[][]; k: number; fused: string[] }[]>(
    "rrf.json",
  );

  it("vector counts are pinned", () => {
    expect({ cases: cases.length }).toEqual(EXPECTED_COUNTS);
  });

  for (const [i, c] of cases.entries()) {
    it(`rrf case ${i}`, () => {
      expect(rrfFuse(c.lists, c.k)).toEqual(c.fused);
    });
  }
});
