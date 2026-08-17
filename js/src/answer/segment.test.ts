import { describe, expect, it } from "vitest";

import { loadCase, loadData } from "../conform/fixtures.js";
import { ABBREVIATIONS, splitClaims, TERMINATORS } from "./segment.js";

interface SegCase {
  text: string;
  claims: string[];
}

// The ADR-0009 segmentation contract: every case in
// conformance/cases/segmentation.json splits exactly as the Python reference —
// abbreviations, initials, decimals, terminator runs, CJK terminators, and the
// hard-newline rule.
/** Vector counts, pinned. A vector silently dropped from the fixture is a
 *  weakened contract that no per-case assertion can see. */
const EXPECTED_COUNTS: Record<string, number> = { cases: 95 };

describe("splitClaims conformance", () => {
  const cases = loadCase<SegCase[]>("segmentation.json");

  it("vector counts are pinned", () => {
    expect({ cases: cases.length }).toEqual(EXPECTED_COUNTS);
  });

  for (const c of cases) {
    it(`splitClaims(${JSON.stringify(c.text)})`, () => {
      expect(splitClaims(c.text)).toEqual(c.claims);
    });
  }
});

describe("segmentation table", () => {
  // ADR-0010 tier 2: one canonical definition, no hand-maintained copy.
  it("matches conformance/segmentation.json exactly", () => {
    const canonical = loadData<{ terminators: string[]; abbreviations: string[] }>(
      "segmentation.json",
    );
    expect([...TERMINATORS].sort()).toEqual([...canonical.terminators].sort());
    expect([...ABBREVIATIONS].sort()).toEqual([...canonical.abbreviations].sort());
  });
});

describe("splitClaims portability traps", () => {
  // JS indexes by UTF-16 code unit; Python indexes by code point. Scanning the
  // string directly would split an astral character in half.
  it("scans by code point, not UTF-16 unit", () => {
    expect(splitClaims("𝔄 test. 𝔅 next.")).toEqual(["𝔄 test.", "𝔅 next."]);
  });

  // String.prototype.trim() strips U+FEFF, Python's str.strip() does not.
  it("trims exactly Python's whitespace set", () => {
    expect(splitClaims("﻿hello.")).toEqual(["﻿hello."]);
    expect(splitClaims("hello.")).toEqual(["hello."]);
  });
});
