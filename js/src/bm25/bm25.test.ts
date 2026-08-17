import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import { bm25, type Bm25Row, type Bm25Result } from "./bm25.js";

// BM25 is proven against the shared fixture — every case must match the Python
// reference exactly (scores rounded to 1e-6). Follows the tokenize exemplar:
// load conformance/cases/bm25.json, assert deep equality over ALL cases.
interface Bm25Case {
  name: string;
  rows: Bm25Row[];
  query: string;
  expected: Bm25Result[];
}

/** Vector counts, pinned. A vector silently dropped from the fixture is a
 *  weakened contract that no per-case assertion can see. */
const EXPECTED_COUNTS: Record<string, number> = { cases: 4 };

describe("bm25 conformance", () => {
  const cases = loadCase<Bm25Case[]>("bm25.json");

  it("vector counts are pinned", () => {
    expect({ cases: cases.length }).toEqual(EXPECTED_COUNTS);
  });

  for (const c of cases) {
    it(c.name, () => {
      expect(bm25(c.rows, c.query)).toEqual(c.expected);
    });
  }
});
