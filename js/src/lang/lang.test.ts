import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import { resolveAnswerLanguage, type LanguageResult } from "./lang.js";

// Proven against the shared fixture — every case must match the Python reference
// citenexus.lang.fallback.resolve_answer_language exactly. Follows the §4
// exemplar: load conformance/cases/language.json, assert equality over ALL
// cases, no leniency.
interface LangCase {
  name: string;
  detection: LanguageResult | null;
  answer_language: string | null;
  conversation_language: string | null;
  languages_in_evidence: string[];
  default_answer_language: string;
  expected: string;
}

describe("resolve_answer_language conformance", () => {
  const cases = loadCase<LangCase[]>("language.json");

  it("has cases", () => {
    expect(cases.length).toBeGreaterThan(0);
  });

  for (const c of cases) {
    it(c.name, () => {
      expect(
        resolveAnswerLanguage({
          detection: c.detection,
          answer_language: c.answer_language,
          conversation_language: c.conversation_language,
          languages_in_evidence: c.languages_in_evidence,
          default_answer_language: c.default_answer_language,
        }),
      ).toEqual(c.expected);
    });
  }
});
