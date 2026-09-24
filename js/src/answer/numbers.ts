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
} from "../gen/conflict_tables.js";

/** Languages whose decimal mark is the comma (ADR-0010 tier 2). */
export const DECIMAL_COMMA_LANGUAGES: ReadonlySet<string> = new Set(DECIMAL_COMMA_LANGUAGES_TABLE);
/** Languages whose decimal mark is the point (ADR-0010 tier 2). */
export const DECIMAL_POINT_LANGUAGES: ReadonlySet<string> = new Set(DECIMAL_POINT_LANGUAGES_TABLE);

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
    return known(valueOf(groups, ""));
  }

  const hasDot = raw.includes(".");
  const hasComma = raw.includes(",");
  if (!hasDot && !hasComma) return known(valueOf([raw], ""));

  if (hasDot && hasComma) {
    const decimalMark = raw.lastIndexOf(".") > raw.lastIndexOf(",") ? "." : ",";
    const thousandsMark = decimalMark === "." ? "," : ".";
    const cut = raw.lastIndexOf(decimalMark);
    const whole = raw.slice(0, cut);
    const decimals = raw.slice(cut + 1);
    if (whole.includes(decimalMark)) return unread(raw);
    const groups = whole.split(thousandsMark);
    if (!isThousands(groups)) return unread(raw);
    return known(valueOf(groups, decimals));
  }

  const mark = hasDot ? "." : ",";
  const parts = raw.split(mark);
  if (parts.length > 2) {
    return isThousands(parts) ? known(valueOf(parts, "")) : unread(raw);
  }

  const whole = parts[0] as string;
  const tail = parts[1] as string;
  if (tail.length !== 3 || !isThousands(parts)) {
    return known(valueOf([whole], tail)); // a decimal mark in every locale
  }

  const languageCode = primary(options.language);
  let thousands: boolean;
  if (DECIMAL_COMMA_LANGUAGES.has(languageCode)) {
    thousands = mark === ".";
  } else if (DECIMAL_POINT_LANGUAGES.has(languageCode)) {
    thousands = mark === ",";
  } else {
    return unread(raw); // 1.500 / 1,500 with no declared locale
  }
  return thousands ? known(valueOf([whole, tail], "")) : known(valueOf([whole], tail));
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
