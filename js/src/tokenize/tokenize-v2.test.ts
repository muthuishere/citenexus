// The ADR-0011 per-script golden matrix. The CLAIM (SUPPORTED_SCRIPTS) and the
// EVIDENCE for it (conformance/cases/tokenize_v2.json) are checked against each
// other here: no script may be claimed as supported without a golden fixture.
import { describe, expect, it } from "vitest";

import { loadCase } from "../conform/fixtures.js";
import { isSupportedV2 } from "../gate/verify-v2.js";
import { tokenize } from "./tokenize.js";
import {
  CONTINUOUS_SCRIPTS,
  SCRIPT_RANGES_FOR_TEST,
  SUPPORTED_SCRIPTS,
  TOKENIZER_VERSION,
  tokenizeV2,
  unsupportedScripts,
} from "./tokenize-v2.js";

interface ScriptCase {
  script: string;
  text: string;
  tokens: string[];
  v1_tokens: string[];
  self_supported: boolean;
  unrelated_supported: boolean;
  unsupported_scripts: string[];
}

interface TokenizeV2Fixture {
  tokenizer_version: number;
  supported_scripts: string[];
  continuous_scripts: string[];
  unrelated_passage: string;
  supported: ScriptCase[];
  unclaimed: { script: string; text: string; unsupported_scripts: string[] }[];
  unicode: { input: string; tokens: string[] }[];
}

const FIXTURE = loadCase<TokenizeV2Fixture>("tokenize_v2.json");

describe("tokenizeV2 conformance (ADR-0011)", () => {
  it("the fixture pins the tokenizer version", () => {
    expect(FIXTURE.tokenizer_version).toBe(TOKENIZER_VERSION);
  });

  it("the claim and its evidence are the same artifact", () => {
    expect([...SUPPORTED_SCRIPTS].sort()).toEqual(FIXTURE.supported_scripts);
    expect([...CONTINUOUS_SCRIPTS].sort()).toEqual(FIXTURE.continuous_scripts);
    expect(new Set(FIXTURE.supported.map((c) => c.script))).toEqual(new Set(SUPPORTED_SCRIPTS));
  });

  // A mis-sorted table would silently mis-classify via the binary search.
  it("the script range table is sorted and disjoint", () => {
    for (let i = 1; i < SCRIPT_RANGES_FOR_TEST.length; i += 1) {
      expect(SCRIPT_RANGES_FOR_TEST[i - 1]![1]).toBeLessThan(SCRIPT_RANGES_FOR_TEST[i]![0]);
    }
  });

  it.each(FIXTURE.supported)("$script tokenizes", (c) => {
    expect(tokenizeV2(c.text)).toEqual(c.tokens);
    expect(c.tokens.length).toBeGreaterThan(0);
  });

  // v1 must NOT be "fixed" — the shipped vectors and every index already built
  // under it depend on the ASCII behavior.
  it.each(FIXTURE.supported)("$script keeps the v1 defect pinned", (c) => {
    expect(tokenize(c.text)).toEqual(c.v1_tokens);
  });

  it.each(FIXTURE.supported)("$script reports no capability gap", (c) => {
    expect(unsupportedScripts(c.text)).toEqual([]);
    expect(c.unsupported_scripts).toEqual([]);
  });

  // Both halves must hold or the script is not supported: the gate accepts a
  // verbatim quote of its own source, AND it still rejects unrelated text.
  it.each(FIXTURE.supported)("$script supports a verbatim quote of its own source", (c) => {
    expect(c.self_supported).toBe(true);
    expect(isSupportedV2(c.text, c.text)).toBe(true);
  });

  it.each(FIXTURE.supported)("$script does not turn the gate into a rubber stamp", (c) => {
    expect(c.unrelated_supported).toBe(false);
    expect(isSupportedV2(c.text, FIXTURE.unrelated_passage)).toBe(false);
  });

  it("the unclaimed half of the matrix is not empty", () => {
    expect(FIXTURE.unclaimed.length).toBeGreaterThan(0);
  });

  it.each(FIXTURE.unclaimed)("$script is reported as a capability gap", (c) => {
    expect(SUPPORTED_SCRIPTS.has(c.script)).toBe(false);
    expect(unsupportedScripts(c.text)).toEqual(c.unsupported_scripts);
    expect(c.unsupported_scripts).toEqual([c.script]);
  });

  it.each(FIXTURE.unicode)("unicode mechanics: $input", (c) => {
    expect(tokenizeV2(c.input)).toEqual(c.tokens);
  });

  // v2 is a strict superset of v1 on pure-ASCII input — that equivalence is why
  // moving BM25 and the gate onto v2 left every shipped vector unchanged.
  it("agrees with v1 on every ASCII v1 vector", () => {
    const cases = loadCase<{ input: string; tokens: string[] }[]>("tokenize.json");
    expect(cases.length).toBeGreaterThan(0);
    for (const c of cases) {
      if (Array.from(c.input).some((ch) => ch.codePointAt(0)! > 127)) continue;
      expect(tokenizeV2(c.input)).toEqual(tokenize(c.input));
    }
  });
});
