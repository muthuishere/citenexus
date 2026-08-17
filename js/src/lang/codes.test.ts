// The named code sets are pinned to conformance/cases/languages.json, which the
// Python reference generates. Python, Go and JS each assert against the same
// file, so the 41 codes cannot diverge by review error — the same three-way pin
// the ADR-0011 script CLAIM already has in tokenize-v2.test.ts.
//
// The compatibility half matters as much as the parity half: a plain string is
// assignable to every public parameter type here, forever. `enum` would have
// made that a type error, which is why this port uses a const object.
import { describe, expect, it } from "vitest";

import { loadCase } from "../conform/fixtures.js";
import { AUTO_ANSWER_LANGUAGE } from "./lang.js";
import {
  Language,
  type LanguageLike,
  SEARCH_LANGUAGES,
  Script,
  type ScriptLike,
  searchLanguageByCode,
} from "./codes.js";

interface LanguagesFixture {
  auto_sentinel: string;
  scripts: string[];
  supported_scripts: string[];
  continuous_scripts: string[];
  languages: { code: string; name: string; scripts: string[]; supported: boolean }[];
}

const FIXTURE = loadCase<LanguagesFixture>("languages.json");

/** Bucket sizes, pinned. A vector silently dropped from a bucket is a weakened
 *  contract that no per-case assertion can see. (`auto_sentinel` is a scalar,
 *  not a bucket, and is asserted by name below.) */
const EXPECTED_COUNTS: Record<string, number> = {
  scripts: 27,
  supported_scripts: 14,
  continuous_scripts: 7,
  languages: 41,
};

describe("languages.json bucket shape", () => {
  it("bucket names and sizes are pinned", () => {
    const sizes = Object.fromEntries(
      Object.entries(FIXTURE)
        .filter(([, v]) => Array.isArray(v))
        .map(([k, v]) => [k, (v as unknown[]).length]),
    );
    expect(sizes).toEqual(EXPECTED_COUNTS);
  });
});

describe("language / script code sets (conformance)", () => {
  it("the search table matches the fixture, in order", () => {
    expect(
      SEARCH_LANGUAGES.map((l) => ({
        code: l.code,
        name: l.name,
        scripts: [...l.scripts],
        supported: l.supported,
      })),
    ).toEqual(FIXTURE.languages);
  });

  it("the Language members are the search codes plus the auto sentinel", () => {
    const members = new Set<string>(Object.values(Language));
    const codes = new Set(FIXTURE.languages.map((l) => l.code));
    codes.add(FIXTURE.auto_sentinel);
    expect(members).toEqual(codes);
    expect(FIXTURE.languages).toHaveLength(41);
  });

  it("the Script members match the fixture", () => {
    expect([...Object.values(Script)].sort()).toEqual([...FIXTURE.scripts].sort());
  });

  it("the auto sentinel is named but is not searchable", () => {
    expect(Language.AUTO).toBe(FIXTURE.auto_sentinel);
    expect(AUTO_ANSWER_LANGUAGE).toBe(Language.AUTO);
    expect(searchLanguageByCode(Language.AUTO)).toBeUndefined();
  });
});

describe("plain strings stay first-class", () => {
  it("a bare string is assignable to LanguageLike and ScriptLike", () => {
    // The compile-time half of the pin: if these ever become a TS `enum`, the
    // next three lines stop type-checking and `npm run typecheck` fails.
    const fromLiteral: LanguageLike = "ta";
    const computed: LanguageLike = ["t", "a"].join("");
    const script: ScriptLike = "tamil";
    expect(fromLiteral).toBe(Language.TAMIL);
    expect(computed).toBe(Language.TAMIL);
    expect(script).toBe(Script.TAMIL);
  });

  it("lookup by a plain string and by a member are the same entry", () => {
    expect(searchLanguageByCode("ta")).toBe(searchLanguageByCode(Language.TAMIL));
    expect(searchLanguageByCode("ta")?.name).toBe("Tamil");
  });

  it("a typo resolves to nothing — codes are never guessed", () => {
    expect(searchLanguageByCode("tamiil")).toBeUndefined();
  });

  it("the answer-language chain takes a string or a member identically", () => {
    // resolveAnswerLanguage is the pinned §11a function; both forms are one call.
    expect(Language.TAMIL === "ta").toBe(true);
    expect(JSON.stringify({ answer_language: Language.TAMIL })).toBe('{"answer_language":"ta"}');
  });
});

describe("the refusal set is carried, not dropped", () => {
  it("names the languages it cannot search", () => {
    const unsupported = SEARCH_LANGUAGES.filter((l) => !l.supported).map((l) => l.code);
    expect(unsupported).toContain(Language.KANNADA);
    // Telugu IS claimed (it has a fixture); its Indic neighbours are not.
    expect(SEARCH_LANGUAGES.find((l) => l.code === Language.TELUGU)?.supported).toBe(true);
  });

  it("every script the table names is a declared Script", () => {
    const declared = new Set<string>(Object.values(Script));
    for (const l of SEARCH_LANGUAGES) {
      for (const s of l.scripts) expect(declared.has(s)).toBe(true);
    }
  });
});
