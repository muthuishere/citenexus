// Guarded claim segmentation (ADR-0009, ADR-0010 tier 1).
//
// An answer is decomposed into atomic claims so each can be verified against its
// cited passage independently. Splitting on punctuation alone is not good
// enough: the naive `[.!?\n]+` splitter failed 54.2% of the ADR-0009 spike's
// six-language cases — abbreviations, decimals and CJK terminators all break it.
//
// Tier-1 scanning code over the tier-2 table in conformance/segmentation.json
// (the single canonical definition, read the same way the stopword list is —
// never a hand-maintained copy). Adding `。！？` to the *table* fixed 100% of the
// Japanese failures with no algorithm change, which is why claim segmentation
// stays native per port rather than moving to the Rust core.
//
// Portability notes, all load-bearing, and together why this is a hand-written
// scanner with no regex in it:
//
//   - Python's `re.escape` emits `\!`, a COMPILE ERROR in Go's RE2 — so the
//     character classes are written literally, and the JS port matches the Go
//     one rather than reintroducing a regex only one port can compile.
//   - `\s` is Unicode-aware in Python but ASCII-only in RE2; whitespace is
//     spelled out explicitly here.
//   - JS strings index by UTF-16 CODE UNIT while Python indexes by CODE POINT,
//     so the scanner runs over `Array.from(text)`. Indexing the string directly
//     would split any astral-plane character in half.
//   - `String.prototype.trim()` is NOT Python's `str.strip()`: it trims U+FEFF,
//     which Python does not, and skips U+001C–U+001F, which Python does trim.
//     `pyStrip` below reproduces Python's set exactly.

import { SEGMENTATION_TABLE as TABLE } from "../gen/tables.js";

/** Sentence terminators, including the CJK and Arabic/Indic forms. */
export const TERMINATORS: ReadonlySet<string> = new Set(TABLE.terminators);
/** Tokens that end in a terminator without ending a sentence. */
export const ABBREVIATIONS: ReadonlySet<string> = new Set(TABLE.abbreviations);

// Spelled out rather than `\s` — see the module docstring. This is the short set
// the SPLITTER consults (rule 4 and preceding-word scanning); it is NOT the
// wider set used to trim a finished claim.
const WHITESPACE = " \t\n\r\f\v\u00a0\u3000";

// Terminators that require whitespace (or end-of-text) after them to count as a
// break. CJK and Arabic/Indic terminators break unconditionally, because those
// scripts do not put a space after the mark.
const NEEDS_TRAILING_SPACE = ".!?";

/** True for exactly the characters Python's `str.isspace()` accepts. */
function pyIsSpace(ch: string): boolean {
  if (" \t\n\v\f\r\u001c\u001d\u001e\u001f\u0085\u00a0\u1680\u2028\u2029\u202f\u205f\u3000".includes(ch)) {
    return true;
  }
  const cp = ch.codePointAt(0) ?? 0;
  return cp >= 0x2000 && cp <= 0x200a;
}

/**
 * In-range indexed read. Every call site below is bounds-checked by the loop
 * that owns it; the cast only silences `noUncheckedIndexedAccess`.
 */
function at(chars: readonly string[], i: number): string {
  return chars[i] as string;
}

/** Python's `str.strip()` with no argument. */
function pyStrip(chars: readonly string[]): string {
  let start = 0;
  let end = chars.length;
  while (start < end && pyIsSpace(at(chars, start))) start++;
  while (end > start && pyIsSpace(at(chars, end - 1))) end--;
  return chars.slice(start, end).join("");
}

// Python's `str.isalpha()` on a single character is Unicode general category L.
const LETTER = /\p{L}/u;

function isDigit(ch: string): boolean {
  return ch >= "0" && ch <= "9";
}

/** The token immediately before the terminator run, lowercased. */
function precedingWord(buffer: readonly string[]): string {
  let end = buffer.length;
  while (end > 0 && TERMINATORS.has(at(buffer, end - 1))) end--;
  let start = end;
  while (start > 0 && !WHITESPACE.includes(at(buffer, start - 1))) start--;
  // JS `toLowerCase` applies Unicode FULL case mapping, matching Python's
  // `str.lower()` — including U+0130 (İ) → "i" + U+0307, which is two code
  // points and therefore NOT a single-letter initial.
  return buffer.slice(start, end).join("").toLowerCase();
}

/**
 * Split `text` into atomic claims on guarded sentence boundaries.
 * Deterministic: the same text always yields the same claims.
 *
 * Rules, applied in order and all local to the break candidate:
 *
 *  1. a run of terminators is one candidate boundary, not several;
 *  2. no break when the terminator sits between two digits (`500.00`);
 *  3. no break when the preceding token is a known abbreviation, or a single
 *     letter (initials — `J. Smith`);
 *  4. no break for space-using scripts unless whitespace or end-of-text follows.
 *
 * A hard line break always ends a claim: pooled evidence and list items are
 * newline-joined, and dropping that rule silently merges them into one
 * unverifiable claim.
 */
export function splitClaims(text: string): string[] {
  const chars = Array.from(text); // code points, not UTF-16 units
  const n = chars.length;
  const claims: string[] = [];
  let buffer: string[] = [];

  for (let i = 0; i < n; i++) {
    const ch = at(chars, i);
    buffer.push(ch);

    if (ch === "\n") {
      const claim = pyStrip(buffer);
      if (claim) claims.push(claim);
      buffer = [];
      continue;
    }

    if (!TERMINATORS.has(ch)) continue;

    // rule 1 — consume the whole terminator run ("?!", "...")
    while (i + 1 < n && TERMINATORS.has(at(chars, i + 1))) {
      i++;
      buffer.push(at(chars, i));
    }

    const following = i + 1 < n ? at(chars, i + 1) : "";
    const preceding = i > 0 ? at(chars, i - 1) : "";

    // rule 2 — decimal, e.g. "500.00"
    if (preceding !== "" && isDigit(preceding) && following !== "" && isDigit(following)) continue;

    // rule 3 — abbreviation or initial
    const word = precedingWord(buffer);
    const wordChars = Array.from(word);
    if (ABBREVIATIONS.has(word) || (wordChars.length === 1 && LETTER.test(at(wordChars, 0)))) continue;

    // rule 4 — space-using scripts need whitespace or end-of-text
    if (following !== "" && !WHITESPACE.includes(following) && NEEDS_TRAILING_SPACE.includes(ch)) {
      continue;
    }

    const claim = pyStrip(buffer);
    if (claim) claims.push(claim);
    buffer = [];
  }

  const tail = pyStrip(buffer);
  if (tail) claims.push(tail);
  return claims;
}
