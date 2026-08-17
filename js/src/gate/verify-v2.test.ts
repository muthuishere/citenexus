import { describe, expect, it } from "vitest";

import { loadCase, loadData } from "../conform/fixtures.js";
import { isSupported } from "./gate.js";
import { align, isSupportedV2, MAX_SINGLE_GAP, MAX_TOTAL_GAP, POLARITY_MARKERS } from "./verify-v2.js";

interface V2Case {
  name: string;
  passage: string;
  answer: string;
  supported: boolean;
}

interface V2Fixture {
  attacks: V2Case[];
  controls: V2Case[];
}

// The ADR-0009 contract: every verdict in conformance/cases/faithful_v2.json is
// reproduced exactly. The attacks are nine false answers the frozen v1 predicate
// accepts 9/9; the controls are legitimately-supported answers in four shapes
// (verbatim, subspan, punctuation/case noise, interior-word compression) that
// must stay accepted — measured false rejection is 0.0%.
/** Bucket sizes, pinned. A vector silently dropped from a bucket is a weakened
 *  contract that no per-case assertion can see. */
const EXPECTED_COUNTS: Record<string, number> = { attacks: 9, controls: 30 };

describe("isSupportedV2 conformance", () => {
  const fixture = loadCase<V2Fixture>("faithful_v2.json");

  it("bucket names and sizes are pinned", () => {
    const sizes = Object.fromEntries(
      Object.entries(fixture).map(([k, v]) => [k, (v as unknown[]).length]),
    );
    expect(sizes).toEqual(EXPECTED_COUNTS);
  });

  for (const c of [...fixture.attacks, ...fixture.controls]) {
    it(`${c.name}: ${c.supported ? "accepted" : "rejected"}`, () => {
      expect(isSupportedV2(c.answer, c.passage)).toBe(c.supported);
    });
  }

  it("is strictly narrower than the frozen v1 predicate", () => {
    for (const c of [...fixture.attacks, ...fixture.controls]) {
      if (isSupportedV2(c.answer, c.passage)) {
        expect(isSupported(c.answer, c.passage), `${c.name}: v2 accepted what v1 rejected`).toBe(
          true,
        );
      }
    }
  });

  it("documents the hole: v1 accepts every adversarial answer", () => {
    const accepted = fixture.attacks.filter((c) => isSupported(c.answer, c.passage)).length;
    expect(accepted).toBe(fixture.attacks.length);
  });
});

describe("polarity table", () => {
  // ADR-0010 tier 2: one canonical definition, no hand-maintained copy.
  it("matches conformance/polarity.json exactly", () => {
    const canonical = loadData<{ markers: string[] }>("polarity.json");
    expect([...POLARITY_MARKERS].sort()).toEqual([...canonical.markers].sort());
  });
});

describe("align", () => {
  const passage = [
    "the",
    "contractor",
    "shall",
    "maintain",
    "liability",
    "insurance",
    "at",
    "all",
    "times",
  ];

  it("returns the minimal-gap span for an ordered, gapped subsequence", () => {
    expect(align(["contractor", "maintain", "insurance"], passage)).toEqual({
      start: 1,
      end: 5,
      totalGap: 2,
      maxGap: 1,
    });
  });

  it("rejects out-of-order tokens and empty inputs", () => {
    expect(align(["insurance", "contractor"], passage)).toBeNull();
    expect(align([], passage)).toBeNull();
    expect(align(["contractor"], [])).toBeNull();
  });

  it("pins the gap budget", () => {
    expect([MAX_SINGLE_GAP, MAX_TOTAL_GAP]).toEqual([4, 8]);
    expect(align(["a", "b"], ["a", "x", "x", "x", "x", "b"])).not.toBeNull();
    expect(align(["a", "b"], ["a", "x", "x", "x", "x", "x", "b"])).toBeNull();
  });
});
