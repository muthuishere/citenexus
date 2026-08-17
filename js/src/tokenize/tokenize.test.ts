import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import { tokenize } from "./tokenize.js";

// The tokenizer is proven against the shared fixture — every case must match the
// Python reference exactly. This is the EXEMPLAR every §4 algorithm test in this
// port follows: load conformance/cases/<algo>.json, assert deep equality over
// ALL cases, no leniency.
/** Vector counts, pinned. A vector silently dropped from the fixture is a
 *  weakened contract that no per-case assertion can see. */
const EXPECTED_COUNTS: Record<string, number> = { cases: 11 };

describe("tokenize conformance", () => {
  const cases = loadCase<{ input: string; tokens: string[] }[]>("tokenize.json");

  it("vector counts are pinned", () => {
    expect({ cases: cases.length }).toEqual(EXPECTED_COUNTS);
  });

  for (const c of cases) {
    it(`tokenize(${JSON.stringify(c.input)})`, () => {
      expect(tokenize(c.input)).toEqual(c.tokens);
    });
  }
});
