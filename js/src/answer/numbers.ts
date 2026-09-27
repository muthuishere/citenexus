// Locale-aware number reading for conflict detection (ADR-0015).
//
// A port of the Python reference `python/src/citenexus/answer/numbers.py`.
//
// Two passages quoting the same amount must compare EQUAL, and two different
// amounts must never compare equal. The second rule dominates: a false "equal"
// hides a real conflict (fails open), while a false "different" only costs an
// abstention (fails closed).
//
// So a number is read to a single value only when its FORM, or the passage's
// declared language, leaves one reading. Otherwise it stays AMBIGUOUS: its key
// is its raw spelling, prefixed `?`, and it is equal to nothing but the same
// spelling. Ambiguity never guesses.
//
// Forms (`.` and `,` are the only separators read):
//
//   * `1500` — an integer.
//   * `25,-` — Dutch whole amount: 25.
//   * both separators — the LAST is the decimal mark, the other groups
//     thousands in threes: `1.500,50` = `1,500.50` = 1500.5.
//   * one separator, repeated — thousands in threes: `1.500.000` = 1500000.
//   * one separator, once, NOT followed by exactly three digits — a decimal mark
//     in every locale: `25,50` = `25.50` = 25.5.
//   * one separator, once, where the whole part cannot lead a thousands group
//     (`1234.567`, `0.500`) — a decimal mark, likewise.
//   * one separator, once, followed by exactly three digits — `1.500` / `1,500`
//     is 1500 or 1.5 depending on the locale. Read only when the language is
//     declared; ambiguous otherwise.
//   * anything else (`1.50.000`, dates `01.02.2024`) — unreadable, kept by
//     spelling.
//
// Values are EXACT: a `bigint` scaled by a power of ten, never a float. Python
// uses `fractions.Fraction`; every value this reader produces is a finite
// decimal, so a scaled integer is the same rational.

import {
  DECIMAL_COMMA_LANGUAGES_TABLE,
  DECIMAL_POINT_LANGUAGES_TABLE,
  LAKH_GROUPING_LANGUAGES_TABLE,
} from "../gen/conflict_tables.js";
import { GS, findAll, goLower, pad2, replaceAll } from "./gotext.js";
import { unitOf } from "./verify-guards-model.js";

/** Languages whose decimal mark is the comma (ADR-0010 tier 2). */
export const DECIMAL_COMMA_LANGUAGES: ReadonlySet<string> = new Set(DECIMAL_COMMA_LANGUAGES_TABLE);
/** Languages whose decimal mark is the point (ADR-0010 tier 2). */
export const DECIMAL_POINT_LANGUAGES: ReadonlySet<string> = new Set(DECIMAL_POINT_LANGUAGES_TABLE);
/** Languages that read Indian lakh grouping, "1,00,000" (ADR-0015 amendment). */
export const LAKH_GROUPING_LANGUAGES: ReadonlySet<string> = new Set(LAKH_GROUPING_LANGUAGES_TABLE);

// Exactly the characters Python's `str.isspace()` accepts. Python's `\s` on a
// `str` is neither JS's `\s` (which adds U+FEFF) nor RE2's (ASCII only), so it
// is spelled out, the same way `segment.ts` spells it out.
const PY_SPACE =
  " \\t\\n\\v\\f\\r\\u001c-\\u001f\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";

/** A number: digit groups joined by single `.`/`,`, an optional Dutch `,-`,
 *  then an optional unit. Applied to LOWERED text. RE2-compatible. `g` is
 *  required for `matchAll` in JS; Python's `finditer` needs no flag. */
export const NUMBER_RE = new RegExp(
  `([0-9]+(?:[.,][0-9]+)*)(,-)?[${PY_SPACE}]*([a-z]+|%)?`,
  "g",
);

const GROUP = /^[0-9]{3}$/;
const LEAD = /^[1-9][0-9]{0,2}$/;
const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, "g");

/** An exact decimal: `units / 10**scale`. */
export interface DecimalValue {
  readonly units: bigint;
  readonly scale: number;
}

/** A number's comparison key and, when it has one reading, its value. */
export interface NumberReading {
  key: string;
  /** `null` = ambiguous or unreadable. */
  value: DecimalValue | null;
}

function primary(language: string | null | undefined): string {
  if (!language) return "";
  return (language.replace(PY_STRIP, "").toLowerCase().split(/[-_]/)[0] ?? "") as string;
}

/** 1-2 leading digits, two-digit groups, a final three-digit group, an
 *  optional point decimal. */
const LAKH = /^([1-9][0-9]?(?:,[0-9]{2})+,[0-9]{3})(?:\.([0-9]+))?$/;

function localeTags(language: string | null | undefined): [string, string] {
  const full = (language ?? "").replace(PY_STRIP, "").toLowerCase().replaceAll("_", "-");
  return [full, primary(full)];
}

/**
 * The declared language's decimal mark: `","`, `"."`, or `""` when unknown. A
 * region tag in the tables ("de-ch", "es-mx") wins over its language (CLDR,
 * ADR-0015 amendment 2026-09-27).
 */
export function decimalMarkOf(language: string | null | undefined): string {
  for (const code of localeTags(language)) {
    if (code === "") continue;
    if (DECIMAL_COMMA_LANGUAGES.has(code)) return ",";
    if (DECIMAL_POINT_LANGUAGES.has(code)) return ".";
  }
  return "";
}

function readsLakh(language: string | null | undefined): boolean {
  const [full, prim] = localeTags(language);
  return full !== "" && (LAKH_GROUPING_LANGUAGES.has(full) || LAKH_GROUPING_LANGUAGES.has(prim));
}

/** Decimal string with no trailing zeros: 1500, 25.5, 0.05. */
function canonical(value: DecimalValue): string {
  let { units, scale } = value;
  while (scale > 0 && units % 10n === 0n) {
    units /= 10n;
    scale--;
  }
  if (scale === 0) return units.toString();
  const sign = units < 0n ? "-" : "";
  const digits = (units < 0n ? -units : units).toString().padStart(scale + 1, "0");
  return `${sign}${digits.slice(0, -scale)}.${digits.slice(-scale)}`;
}

function valueOf(integerGroups: readonly string[], decimals: string): DecimalValue {
  return { units: BigInt(integerGroups.join("") + decimals), scale: decimals.length };
}

function known(value: DecimalValue): NumberReading {
  return { key: canonical(value), value };
}

const DIGITS = /^[0-9]*$/;

/**
 * `known` over integer groups and decimal digits. A token that is not digits
 * ("4al" — verifyAnswer's guards read tokenizer tokens) gets Go's reading
 * (golang numbers.go `known`): the key trimmed of leading/trailing zeros, and
 * no value, where BigInt would throw.
 */
function knownOf(integerGroups: readonly string[], decimals: string): NumberReading {
  const whole = integerGroups.join("");
  if (DIGITS.test(whole) && DIGITS.test(decimals)) return known(valueOf(integerGroups, decimals));
  const w = whole.replace(/^0+/, "") || "0";
  const d = decimals.replace(/0+$/, "");
  return { key: d === "" ? w : w + "." + d, value: null };
}

function unread(raw: string): NumberReading {
  return { key: "?" + raw, value: null };
}

/** A valid thousands grouping: 1-3 leading digits (no leading zero), then threes. */
function isThousands(groups: readonly string[]): boolean {
  return LEAD.test(groups[0] as string) && groups.slice(1).every((g) => GROUP.test(g));
}

/**
 * Read one matched number (`NUMBER_RE` group 1) to its comparison key.
 *
 * `dash` is true when the Dutch `,-` suffix followed it. `language` is the
 * passage's DECLARED language; only its primary subtag is read.
 */
export function readNumber(
  raw: string,
  options: { dash?: boolean; language?: string | null } = {},
): NumberReading {
  if (options.dash === true) {
    if (raw.includes(",")) return unread(raw + ",-"); // "25,50,-" is not a form
    const groups = raw.split(".");
    if (groups.length > 1 && !isThousands(groups)) return unread(raw + ",-");
    return knownOf(groups, "");
  }

  const hasDot = raw.includes(".");
  const hasComma = raw.includes(",");
  if (!hasDot && !hasComma) return knownOf([raw], "");
  // Indian lakh grouping: a two-digit group can be nothing else, but only a
  // language that writes it reads it.
  const lakh = LAKH.exec(raw);
  if (lakh !== null && readsLakh(options.language)) {
    return knownOf([(lakh[1] as string).replaceAll(",", "")], lakh[2] ?? "");
  }

  if (hasDot && hasComma) {
    const decimalMark = raw.lastIndexOf(".") > raw.lastIndexOf(",") ? "." : ",";
    const thousandsMark = decimalMark === "." ? "," : ".";
    const cut = raw.lastIndexOf(decimalMark);
    const whole = raw.slice(0, cut);
    const decimals = raw.slice(cut + 1);
    if (whole.includes(decimalMark)) return unread(raw);
    const groups = whole.split(thousandsMark);
    if (!isThousands(groups)) return unread(raw);
    return knownOf(groups, decimals);
  }

  const mark = hasDot ? "." : ",";
  const parts = raw.split(mark);
  if (parts.length > 2) {
    return isThousands(parts) ? knownOf(parts, "") : unread(raw);
  }

  const whole = parts[0] as string;
  const tail = parts[1] as string;
  if (tail.length !== 3 || !isThousands(parts)) {
    return knownOf([whole], tail); // a decimal mark in every locale
  }

  const decimalMark = decimalMarkOf(options.language);
  let thousands: boolean;
  if (decimalMark === ",") {
    thousands = mark === ".";
  } else if (decimalMark === ".") {
    thousands = mark === ",";
  } else {
    return unread(raw); // 1.500 / 1,500 with no declared locale
  }
  return thousands ? knownOf([whole, tail], "") : knownOf([whole], tail);
}

/** `|a - b| <= tolerance`, exactly, over scaled integers. */
export function decimalWithin(a: DecimalValue, b: DecimalValue, tolerance: DecimalValue): boolean {
  const scale = Math.max(a.scale, b.scale, tolerance.scale);
  const up = (v: DecimalValue): bigint => v.units * 10n ** BigInt(scale - v.scale);
  const diff = up(a) - up(b);
  return (diff < 0n ? -diff : diff) <= up(tolerance);
}

/** Exact product of two decimals. */
export function decimalMul(a: DecimalValue, b: DecimalValue): DecimalValue {
  return { units: a.units * b.units, scale: a.scale + b.scale };
}

/** Parse an exact decimal string such as `"1.21"` — never via a float. */
export function parseDecimal(text: string): DecimalValue {
  const match = /^(-?)([0-9]+)(?:\.([0-9]+))?$/.exec(text);
  if (match === null) throw new Error(`not a decimal: ${text}`);
  const decimals = match[3] ?? "";
  const units = BigInt((match[2] as string) + decimals);
  return { units: match[1] === "-" ? -units : units, scale: decimals.length };
}

// ─── Beyond the Python reference: the Go port's numbers.go (VerifyAnswer) ─────
//
// Everything below mirrors golang/answer/numbers.go byte for byte in behaviour:
// numbers found in running text (with space-grouped money thousands), clock
// times, money rates and dates. The conflict detector reads numbers through
// `numbersIn` too, exactly as Go's conflictFeaturesOf does.


/** One number found in lowered text, with its unit (if any). */
export interface NumberMatch {
  /** the matched digits and separators, as written */
  raw: string;
  reading: NumberReading;
  unit: string;
  /** the unit follows the digits with no space ("1st", "2de") */
  attached: boolean;
}

const NUMBER_RE_GO = new RegExp(`([0-9]+(?:[.,][0-9]+)*)(,-)?[${PY_SPACE}]*([a-z]+|%)?`, "gd");

/** The letter-boundary guard is LATIN-ONLY (golang isIdentifierPrefix). */
function isIdentifierPrefix(ch: string): boolean {
  return (ch >= "a" && ch <= "z") || ch === "_";
}

/**
 * A number's spelling (`NumberMatch.raw`) in a cited unit -> the unit's own
 * reading of it. ADR-0015 amendment 2026-09-27: a number the claim copies
 * VERBATIM from its unit keeps the unit's locale — an English claim writing
 * the Dutch "€ 4.000" is 4000 over that unit. The match is on the whole matched
 * number, so "12" never takes the reading of "12.75" or "0,12". A spelling the
 * unit reads two ways is dropped: ambiguity falls back to the claim's language.
 */
export type VerbatimNumbers = ReadonlyMap<string, NumberReading>;

/** The unit's verbatim readings, for the claim side of a guard. */
export function verbatimIn(text: string, language: string | null | undefined): VerbatimNumbers {
  const out = new Map<string, NumberReading>();
  const clash = new Set<string>();
  for (const m of numbersIn(text, language)) {
    const seen = out.get(m.raw);
    if (seen !== undefined && seen.key !== m.reading.key) clash.add(m.raw);
    out.set(m.raw, m.reading);
  }
  for (const raw of clash) out.delete(raw);
  return out;
}

/** A claim number: the unit's reading when copied verbatim, else its own. A
 *  dashed amount ("4.000,-") reads the same in every locale. */
export function readWith(
  raw: string,
  dash: boolean,
  language: string | null | undefined,
  verbatim?: VerbatimNumbers,
): NumberReading {
  if (!dash && verbatim !== undefined) {
    const hit = verbatim.get(raw);
    if (hit !== undefined) return hit;
  }
  return readNumber(raw, { dash, language: language ?? "" });
}

/** Every measured number in text, skipping identifiers such as "p50" / "ipv4".
 *  `verbatim`, when given, is the cited unit's readings (claim side only). */
export function numbersIn(
  text: string,
  language: string | null | undefined,
  verbatim?: VerbatimNumbers,
): NumberMatch[] {
  const lowered = joinSpacedThousands(goLower(text), language);
  const out: NumberMatch[] = [];
  for (const m of findAll(NUMBER_RE_GO, lowered)) {
    const g1 = m.groups[0] as readonly [number, number];
    const start = g1[0];
    if (start > 0 && isIdentifierPrefix(lowered[start - 1] as string)) continue;
    const raw = lowered.slice(g1[0], g1[1]);
    const unitAt = m.groups[2];
    out.push({
      raw,
      reading: readWith(raw, m.groups[1] !== null, language, verbatim),
      unit: unitAt === null || unitAt === undefined ? "" : lowered.slice(unitAt[0], unitAt[1]),
      attached: unitAt !== null && unitAt !== undefined && unitAt[0] === g1[1],
    });
  }
  return out;
}

// Clock times are times of day, never durations or amounts: "09:00" = "9:00" =
// "9.00 uur" = "9am".
const CLOCK_COLON = /\b([01]?[0-9]|2[0-3]):([0-5][0-9])\b/dg;
const CLOCK_DOT = new RegExp(`\\b([01]?[0-9]|2[0-3])\\.([0-5][0-9])([${GS}]*(?:uur|u)\\b)`, "dg");
const CLOCK_AMPM = new RegExp(
  `\\b(1[0-2]|0?[1-9])(?:[:.]([0-5][0-9]))?[${GS}]*(am|pm|a\\.m\\.|p\\.m\\.)`,
  "dg",
);

function blankRange(s: string, start: number, end: number): string {
  return s.slice(0, start) + " ".repeat(end - start) + s.slice(end);
}

/** The clock-time keys ("clock:9:00", 24-hour) in text, and the text lowered
 * with them blanked out. */
export function clockTimes(text: string): [Set<string>, string] {
  const keys = new Set<string>();
  const lowered = goLower(text);
  let blank = lowered;
  const mark = (start: number, end: number, hour: string, minute: string): void => {
    let h = hour.replace(/^0+/, "");
    if (h === "") h = "0";
    if (minute === "") minute = "00";
    keys.add(`clock:${h}:${minute}`);
    blank = blankRange(blank, start, end);
  };
  for (const m of findAll(CLOCK_AMPM, lowered)) {
    const hour = m.group(1) as string;
    const minute = m.group(2) ?? "";
    let h = 0;
    for (const r of hour) h = h * 10 + (r.charCodeAt(0) - 48);
    const pm = (m.group(3) as string).startsWith("p");
    if (pm && h < 12) h += 12;
    else if (!pm && h === 12) h = 0;
    mark(m.start, m.end, String(h), minute);
  }
  for (const re of [CLOCK_COLON, CLOCK_DOT]) {
    const snapshot = blank;
    for (const m of findAll(re, snapshot)) {
      const g2 = m.groups[1] as readonly [number, number];
      mark(m.start, g2[1], m.group(1) as string, m.group(2) as string);
    }
  }
  return [keys, blank];
}

// Money is never a duration: "€ 150 per maand" is a price with a period.
const MONEY_BEFORE = new RegExp(`(?:€|\\beur\\b|\\$|£)[${GS}]*([0-9][0-9.,]*)(?:,-)?`, "dgu");
const MONEY_AFTER = new RegExp(`\\b([0-9][0-9.,]*)[${GS}]*(?:euro|eur)\\b`, "dgu");
const RATE_PERIOD = new RegExp(
  `^(?:[${GS}]+\\p{L}+)?[${GS}]*(?:per|a|an|each|/)[${GS}]*(\\p{L}+)`,
  "dgu",
);

/** The money rates in text — "amount key\u0000period class" — and the text
 * lowered with every money amount blanked. */
export function moneyRates(
  text: string,
  language: string,
  verbatim?: VerbatimNumbers,
): [Set<string>, string] {
  const rates = new Set<string>();
  const lowered = goLower(text);
  let blank = lowered;
  for (const re of [MONEY_BEFORE, MONEY_AFTER]) {
    for (const m of findAll(re, lowered)) {
      const g1 = m.groups[0] as readonly [number, number];
      const raw = (m.group(1) as string).replace(/[.,]+$/, "");
      if (raw === "") continue;
      const key = readWith(raw, false, language, verbatim).key;
      const p = findAll(RATE_PERIOD, lowered.slice(m.end))[0];
      if (p !== undefined) {
        const [cls, , ok] = unitOf(p.group(1) as string);
        if (ok) rates.add(`${key}\u0000${cls}`);
      }
      blank = blankRange(blank, g1[0], g1[1]);
    }
  }
  return [rates, blank];
}

// A money amount grouped by spaces — plain, no-break or narrow no-break —
// "€ 4 000" = "€ 4.000" = 4000; only after a currency sign or code, and only
// with exact three-digit groups.
const SPACED_THOUSANDS = new RegExp(
  `((?:€|\\beur\\b|\\$|£)[${GS}\\u00a0\\u202f]*)([1-9][0-9]*)[ \\u00a0\\u202f]([0-9]{3})\\b`,
  "dgu",
);

// Digits grouped by a space (plain, no-break, narrow no-break: "1 234,56") or
// an apostrophe (Swiss "1'234.50" / "1’234.50"): 1-3 leading digits, then
// exact three-digit groups.
const SPACE_GROUPED = /[1-9][0-9]{0,2}(?:[ \u00a0\u202f][0-9]{3})+/gu;
const APOSTROPHE_GROUPED = /[1-9][0-9]{0,2}(?:['\u2019][0-9]{3})+/gu;
const GROUP_SEPARATORS = /[ \u00a0\u202f'\u2019]/gu;
const GROUP_SEPARATOR = /^[ \u00a0\u202f'\u2019]$/u;
const DIGIT_OR_LETTER = /^[\p{Nd}\p{L}]$/u;
const DIGIT = /^\p{Nd}$/u;

function charBefore(text: string, i: number): string {
  const cp = text.codePointAt(i - 1) as number;
  if (i >= 2 && cp >= 0xdc00 && cp <= 0xdfff) return String.fromCodePoint(text.codePointAt(i - 2) as number);
  return String.fromCodePoint(cp);
}

function charAt(text: string, i: number): string {
  return String.fromCodePoint(text.codePointAt(i) as number);
}

/** Remove the separators of each whole grouped run. A run touching another
 *  digit, letter or number mark on either side, or followed by another
 *  separator and a digit ("1 234 56"), stays as written: it may be several
 *  numbers, and ambiguity is never guessed. */
function joinGrouped(text: string, re: RegExp): string {
  let out = "";
  let last = 0;
  for (const m of text.matchAll(re)) {
    const start = m.index;
    const end = start + m[0].length;
    if (start > 0) {
      const prev = charBefore(text, start);
      if (DIGIT_OR_LETTER.test(prev) || ".,'\u2019".includes(prev)) continue;
    }
    if (end < text.length) {
      const next = charAt(text, end);
      if (DIGIT_OR_LETTER.test(next)) continue;
      if (GROUP_SEPARATOR.test(next) && end + next.length < text.length && DIGIT.test(charAt(text, end + next.length))) {
        continue;
      }
    }
    out += text.slice(last, start) + m[0].replace(GROUP_SEPARATORS, "");
    last = end;
  }
  return out + text.slice(last);
}

/** Join grouped digits before numbers are read: a money amount grouped by
 *  spaces in every language; any space-grouped run only in a decimal-comma
 *  language ("1 234,56", CLDR fr, de, …); apostrophe grouping in every
 *  language — an apostrophe is a decimal mark nowhere. */
export function joinSpacedThousands(text: string, language?: string | null): string {
  for (let i = 0; i < 4; i++) {
    const next = replaceAll(SPACED_THOUSANDS, text, "$1$2$3");
    if (next === text) break;
    text = next;
  }
  if (decimalMarkOf(language) === ",") text = joinGrouped(text, SPACE_GROUPED);
  return joinGrouped(text, APOSTROPHE_GROUPED);
}

// Dates, numeric or written, read as (day, month, year?) and compared as dates.
const MONTH_NUMBER: ReadonlyMap<string, number> = new Map([
  ["januari", 1], ["februari", 2], ["maart", 3], ["april", 4], ["mei", 5], ["juni", 6],
  ["juli", 7], ["augustus", 8], ["september", 9], ["oktober", 10], ["november", 11],
  ["december", 12], ["january", 1], ["february", 2], ["march", 3], ["may", 5], ["june", 6],
  ["july", 7], ["august", 8], ["october", 10],
]);
const MONTH_NAMES = [...MONTH_NUMBER.keys()].sort((a, b) => b.length - a.length).join("|");
const NUMERIC_DATE = /\b([0-3]?[0-9])[-/.]([01]?[0-9])(?:[-/.]((?:19|20)[0-9]{2}))?\b/dg;
const DAY_MONTH = new RegExp(
  `\\b([0-3]?[0-9])(?:st|nd|rd|th|e|ste|de)?[${GS}]+(${MONTH_NAMES})\\b(?:[${GS}]+((?:19|20)[0-9]{2}))?`,
  "dg",
);
const MONTH_DAY = new RegExp(
  `\\b(${MONTH_NAMES})[${GS}]+([0-3]?[0-9])(?:st|nd|rd|th)?\\b(?:,?[${GS}]+((?:19|20)[0-9]{2}))?`,
  "dg",
);

/** A date: day, month, year (0 = not stated), or an ambiguous spelling. */
export interface DateKey {
  day: number;
  month: number;
  year: number;
  ambiguous: string;
}

export function dateKeyString(d: DateKey): string {
  if (d.ambiguous !== "") return d.ambiguous;
  if (d.year === 0) return `${pad2(d.day)}-${pad2(d.month)}`;
  return `${pad2(d.day)}-${pad2(d.month)}-${d.year}`;
}

/** Equal day and month, and equal years when both state one. */
export function sameDate(a: DateKey, b: DateKey): boolean {
  if (a.ambiguous !== "" || b.ambiguous !== "") return a.ambiguous !== "" && a.ambiguous === b.ambiguous;
  return a.day === b.day && a.month === b.month && (a.year === 0 || b.year === 0 || a.year === b.year);
}

function atoi(s: string): number {
  let n = 0;
  for (const r of s) n = n * 10 + (r.charCodeAt(0) - 48);
  return n;
}

export interface DateSpan {
  start: number;
  end: number;
  key: DateKey;
}

/** The dates in text, and the text lowered with them blanked. */
export function datesIn(text: string, language: string): [DateKey[], string] {
  const lowered = goLower(text);
  let blank = lowered;
  const out: DateKey[] = [];
  for (const sp of dateSpans(lowered, language)) {
    out.push(sp.key);
    blank = blankRange(blank, sp.start, sp.end);
  }
  return [out, blank];
}

/** The dates in lowered text, in text order. */
export function dateSpans(lowered: string, language: string): DateSpan[] {
  let blank = lowered;
  const spans: DateSpan[] = [];
  const valid = (d: number, m: number): boolean => d >= 1 && d <= 31 && m >= 1 && m <= 12;
  const mark = (start: number, end: number, k: DateKey): void => {
    spans.push({ start, end, key: k });
    blank = blankRange(blank, start, end);
  };
  for (const m of findAll(DAY_MONTH, lowered)) {
    const d = atoi(m.group(1) as string);
    const mo = MONTH_NUMBER.get(m.group(2) as string) ?? 0;
    if (!valid(d, mo)) continue;
    const y = m.group(3);
    mark(m.start, m.end, { day: d, month: mo, year: y === undefined ? 0 : atoi(y), ambiguous: "" });
  }
  for (const m of findAll(MONTH_DAY, blank)) {
    const mo = MONTH_NUMBER.get(m.group(1) as string) ?? 0;
    const d = atoi(m.group(2) as string);
    if (!valid(d, mo)) continue;
    const y = m.group(3);
    mark(m.start, m.end, { day: d, month: mo, year: y === undefined ? 0 : atoi(y), ambiguous: "" });
  }
  const dutch = primary(language) === "nl";
  for (const m of findAll(NUMERIC_DATE, blank)) {
    const raw = m.text;
    const a = atoi(m.group(1) as string);
    const b = atoi(m.group(2) as string);
    let year = 0;
    const y = m.group(3);
    if (y !== undefined) year = atoi(y);
    else if (!raw.includes("-")) continue; // "1.5" or "3/4" without a year
    let k: DateKey;
    if (dutch && valid(a, b)) k = { day: a, month: b, year, ambiguous: "" };
    else if (!dutch && valid(a, b) && valid(b, a) && a !== b) k = { day: 0, month: 0, year: 0, ambiguous: "date?" + raw };
    else if (valid(a, b)) k = { day: a, month: b, year, ambiguous: "" };
    else if (valid(b, a)) k = { day: b, month: a, year, ambiguous: "" }; // month-first, unambiguous
    else continue;
    mark(m.start, m.end, k);
  }
  spans.sort((x, y) => x.start - y.start);
  return spans;
}
