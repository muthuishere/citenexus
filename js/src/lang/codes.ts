// Language and Script — the named code sets (change: language-enums).
//
// A `const` object plus a union type, deliberately NOT a TypeScript `enum`. An
// `enum` is the wrong tool for a published library, for three reasons:
//
//  1. **Nominal typing breaks the string path.** With `enum Language { TAMIL = "ta" }`
//     the type `Language` does NOT accept the literal `"ta"`, so every existing
//     `answerLanguage: "ta"` call site becomes a type error. Strings must keep
//     working, so an `enum` is disqualified before any other consideration.
//  2. **It is not erasable.** `enum` emits runtime code, so it is illegal under
//     `erasableSyntaxOnly` and under Node's built-in type stripping. A library
//     shipping `.d.ts` should not force that on its consumers.
//  3. **It does not tree-shake** — the emitted IIFE is retained whole.
//
// The `(string & {})` arm of `LanguageLike` is the standard trick that keeps IDE
// autocomplete listing the 41 known codes WHILE still accepting any string. That
// is the TS mirror of Python's `str | Language`: the named set is a convenience,
// never a gate.
//
// The set is pinned to <repo>/conformance/cases/languages.json (see
// codes.test.ts), which the Python reference generates.

import { LANGUAGES_TABLE } from "../gen/tables.js";

/** The languages CiteNexus can NAME — including the ones it refuses to search. */
export const Language = {
  ENGLISH: "en",
  FRENCH: "fr",
  GERMAN: "de",
  SPANISH: "es",
  PORTUGUESE: "pt",
  ITALIAN: "it",
  DUTCH: "nl",
  POLISH: "pl",
  TURKISH: "tr",
  VIETNAMESE: "vi",
  INDONESIAN: "id",
  SWAHILI: "sw",
  RUSSIAN: "ru",
  UKRAINIAN: "uk",
  GREEK: "el",
  HEBREW: "he",
  ARABIC: "ar",
  PERSIAN: "fa",
  URDU: "ur",
  HINDI: "hi",
  MARATHI: "mr",
  NEPALI: "ne",
  BENGALI: "bn",
  ASSAMESE: "as",
  TAMIL: "ta",
  THAI: "th",
  KOREAN: "ko",
  CHINESE: "zh",
  JAPANESE: "ja",
  TELUGU: "te",
  KANNADA: "kn",
  MALAYALAM: "ml",
  GUJARATI: "gu",
  PUNJABI: "pa",
  ODIA: "or",
  SINHALA: "si",
  KHMER: "km",
  LAO: "lo",
  BURMESE: "my",
  GEORGIAN: "ka",
  ARMENIAN: "hy",

  /**
   * "detect it from my question" — a sentinel, not a language. Deliberately
   * absent from `SEARCH_LANGUAGES`, so asking to SEARCH `"auto"` still fails as
   * an unknown code. Equal to `AUTO_ANSWER_LANGUAGE`.
   */
  AUTO: "auto",
} as const;

/** A known language code. Prefer `LanguageLike` in public signatures. */
export type Language = (typeof Language)[keyof typeof Language];

/**
 * What public signatures take: a known code, or any string. The `string & {}`
 * arm keeps the 41 known codes in autocomplete without ever rejecting a
 * caller's computed string.
 */
// eslint-disable-next-line @typescript-eslint/ban-types
export type LanguageLike = Language | (string & {});

/** The writing systems the tokenizer's script table classifies (ADR-0011). */
export const Script = {
  ARABIC: "arabic",
  ARMENIAN: "armenian",
  BENGALI: "bengali",
  COMMON: "common",
  CYRILLIC: "cyrillic",
  DEVANAGARI: "devanagari",
  GEORGIAN: "georgian",
  GREEK: "greek",
  GUJARATI: "gujarati",
  GURMUKHI: "gurmukhi",
  HAN: "han",
  HANGUL: "hangul",
  HEBREW: "hebrew",
  HIRAGANA: "hiragana",
  KANNADA: "kannada",
  KATAKANA: "katakana",
  KHMER: "khmer",
  LAO: "lao",
  LATIN: "latin",
  MALAYALAM: "malayalam",
  MYANMAR: "myanmar",
  ORIYA: "oriya",
  SINHALA: "sinhala",
  TAMIL: "tamil",
  TELUGU: "telugu",
  THAI: "thai",
  UNKNOWN: "unknown",
} as const;

/** A known script name. Prefer `ScriptLike` in public signatures. */
export type Script = (typeof Script)[keyof typeof Script];

// eslint-disable-next-line @typescript-eslint/ban-types
export type ScriptLike = Script | (string & {});

/** One entry of the search-language table. */
export interface SearchLanguage {
  readonly code: Language;
  readonly name: string;
  readonly scripts: readonly Script[];
  /** True when every script this language needs carries an ADR-0011 fixture. */
  readonly supported: boolean;
}

/**
 * The search-language table, in the canonical order of the conformance fixture.
 * Unsupported entries are present ON PURPOSE — dropping them would turn a
 * precise "kannada is not claimed" into a vague "unknown language code".
 */
export const SEARCH_LANGUAGES: readonly SearchLanguage[] =
  LANGUAGES_TABLE as readonly SearchLanguage[];

/**
 * Look a language up by code. A plain string is accepted, so
 * `searchLanguageByCode("ta")` is as valid as `searchLanguageByCode(Language.TAMIL)`.
 * Codes are NEVER guessed: an unknown code returns `undefined` rather than
 * inferring a script from its shape.
 */
export function searchLanguageByCode(code: LanguageLike): SearchLanguage | undefined {
  return SEARCH_LANGUAGES.find((l) => l.code === code);
}
