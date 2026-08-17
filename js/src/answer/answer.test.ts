import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import { ask, type CorpusDoc } from "./answer.js";

// The ask flow is proven against the shared end-to-end fixture — every question
// must yield the expected decision, answer, and cited evidence. Follows the
// tokenize exemplar: load conformance/cases/e2e_hermetic.json, assert over ALL
// cases, no leniency.
interface Expected {
  decision: string;
  answer: string;
  document: string | null;
  passage: string | null;
  eu_id: string | null;
}

interface E2ECase {
  question: string;
  expected: Expected;
}

interface E2EFixture {
  corpus: CorpusDoc[];
  top_k: number;
  cases: E2ECase[];
}

/** Vector counts, pinned. A vector silently dropped from the fixture is a
 *  weakened contract that no per-case assertion can see. `top_k` is a scalar
 *  parameter, not a count, so it is pinned separately. */
const EXPECTED_COUNTS: Record<string, number> = { corpus: 6, cases: 8 };
const EXPECTED_TOP_K = 8;

describe("hermetic ask flow conformance", () => {
  const fixture = loadCase<E2EFixture>("e2e_hermetic.json");

  it("vector counts are pinned", () => {
    expect({ corpus: fixture.corpus.length, cases: fixture.cases.length }).toEqual(
      EXPECTED_COUNTS,
    );
    expect(fixture.top_k).toBe(EXPECTED_TOP_K);
  });

  for (const c of fixture.cases) {
    it(`ask(${JSON.stringify(c.question)})`, () => {
      const r = ask(fixture.corpus, c.question, fixture.top_k);
      const source = r.sources[0] ?? null;
      const euId = r.claims[0]?.sources[0] ?? null;

      expect(r.evidence.decision).toBe(c.expected.decision);
      expect(r.answer).toBe(c.expected.answer);
      expect(source?.document ?? null).toBe(c.expected.document);
      expect(source?.passage ?? null).toBe(c.expected.passage);
      expect(euId).toBe(c.expected.eu_id);
    });
  }
});
