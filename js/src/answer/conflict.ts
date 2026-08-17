// Deterministic conflict detection and near-duplicate collapse (ADR-0007).
//
// A byte-for-byte port of the Python reference
// `python/src/citenexus/answer/conflict.py`. Two questions asked of the *same*
// post-fusion candidate set, by the same pairwise comparison:
//
//   * **Do two grounded passages disagree?** — surfaced, never resolved.
//     Resolution is a policy decision that belongs to the caller and to
//     authority (ADR-0004); a library that silently picks a winner is today's
//     bug with more machinery.
//   * **Are two grounded passages the same passage twice?** — collapsed, so
//     `distinct_documents` stops counting mirrors as independent corroboration.
//
// Both are pure, offline and model-free: set arithmetic plus one RE2-clean
// number pattern. ADR-0010 tier 1 (native per port) over the tier-2 tables in
// `gen/conflict_tables.ts` — no Rust, no FFI, no native library, so plain ESM
// keeps working in a browser or a Cloudflare Worker.
//
// **The number that matters is the false-conflict rate, not recall.** In strict
// mode a detected conflict abstains, so a false conflict is a false refusal,
// while a missed conflict merely leaves today's behaviour in place. Every rule
// below is built to decline rather than decide, and the guard that actually
// holds the rate down is `MAX_RESIDUAL`: see its comment.
//
// Order is load-bearing. **Conflict is checked before duplication.** A one-word
// change is a duplicate only when that word is neither a value nor a polarity
// marker; getting this backwards would collapse a contradiction into a
// corroboration, which is the worst outcome this change could produce.
//
// Portability notes, all load-bearing:
//
//   - Python's `str.replace(",", "")` replaces EVERY comma; JS's replaces only
//     the first. `stripCommas` below uses a global pattern.
//   - Python's `\s` on a `str` is the Unicode set `str.isspace()` accepts, which
//     is neither JS's `\s` (which adds U+FEFF) nor RE2's (ASCII only). It is
//     spelled out explicitly here, the same way `segment.ts` spells it out.
//   - JS `Set` has no portable difference/intersection at this target (ES2022,
//     Node >= 20), so the set arithmetic is written out.
//   - Python `sorted()` on these tokens is code-point order; JS's default
//     `Array.sort()` is code-UNIT order. Since the move to tokenize v2 the token
//     set is no longer ASCII, but the two orders only diverge for supplementary-
//     plane characters (surrogates sort below U+E000-U+FFFF), and no script the
//     tokenizer claims lives there. The sorts are still explicit because `Set`
//     iteration is INSERTION-ordered.

import {
  CONFLICT_ANTONYMS_TABLE,
  CONFLICT_NEGATIONS_TABLE,
  CONFLICT_REPORT_BIGRAMS_TABLE,
  CONFLICT_SCOPE_MARKERS_TABLE,
  CONFLICT_THRESHOLDS_TABLE,
  MEASUREMENT_UNITS_TABLE,
} from "../gen/conflict_tables.js";
import { STOPWORDS_TABLE } from "../gen/tables.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";

// ───────────────────────────────────────────────────────────────────────────
// Pinned constants. None of these are exposed as caller parameters: a
// conformance vector cannot pin a value the caller controls, and every one of
// them trades directly against false abstention. They are READ FROM THE TABLE
// rather than retyped, so a port cannot quietly relax one.
// ───────────────────────────────────────────────────────────────────────────

/** Content-token overlap coefficient required before two passages are treated
 *  as being about the same subject at all. */
export const SUBJECT_OVERLAP = CONFLICT_THRESHOLDS_TABLE.subject_overlap;

/** Total content divergence allowed before the pair is simply unrelated. */
export const MAX_SYMDIFF = CONFLICT_THRESHOLDS_TABLE.max_symdiff;

/** Content divergence allowed *after* removing the polarity signal itself.
 *
 *  This one guard does nearly all the work. Two passages that genuinely
 *  disagree are otherwise word-identical; two that merely look like they
 *  disagree differ by exactly one further content word — the scope
 *  (adults/children), the route (oral/intravenous), the environment
 *  (staging/production), the metric (p50/p99) — and that word is what makes
 *  them complementary. The ADR-0007 spike swept it:
 *
 *      residual  recall  false-conflict rate
 *        0        0.89   0.00
 *        1        0.89   0.00
 *        2        0.93   0.15   <- +4pp recall costs 15pp FALSE ABSTENTION
 *        3        0.93   0.19
 *
 *  Relaxing it by one token is a 15-point mistake. It is a pinned constant. */
export const MAX_RESIDUAL = CONFLICT_THRESHOLDS_TABLE.max_residual;

/** Passages with fewer content tokens than this are not comparable. */
export const MIN_CONTENT = CONFLICT_THRESHOLDS_TABLE.min_content;

/** Token-set Jaccard at which two same-polarity, same-valued passages are
 *  treated as surface clones of each other. */
export const DUPLICATE_JACCARD = CONFLICT_THRESHOLDS_TABLE.duplicate_jaccard;

/** Length difference (in tokens) still allowed for a surface clone. */
export const DUPLICATE_MAX_LENGTH_DELTA = CONFLICT_THRESHOLDS_TABLE.duplicate_max_length_delta;

/** How many post-fusion candidates are compared pairwise. O(k²) on a small k. */
export const CONFLICT_TOP_K = CONFLICT_THRESHOLDS_TABLE.top_k;

// A digit-LEADING token ("500mg", "2019") is a measured value and belongs to
// the numeric rule. A letter-leading token containing digits ("p50", "ipv4",
// "sec4") is an IDENTIFIER and must stay in the content set — it is frequently
// the only thing distinguishing two otherwise-identical passages. Getting this
// backwards produced the spike's only false conflict ("The p50 latency budget
// is 200 ms" vs "The p99 latency budget is 900 ms"), because the digit filter
// ate the one word that told them apart.
const MEASUREMENT_RE = /^[0-9]+[a-z]*$/;

// The identifier exception above is ASCII, for the same reason the letter
// boundary below is. `tokenizeV2` emits CHARACTER BIGRAMS for CJK, so
// 「通知期間は30日です。」 tokenizes as は3 / 30 / 日, and its 60-day counterpart as
// は6 / 60 / 日. `MEASUREMENT_RE` correctly drops the bare 30 and 60, but は3 and
// は6 are letter-leading-with-digit, so the identifier exception kept BOTH in the
// content set — a two-token divergence manufactured out of one number, which is
// above `MAX_RESIDUAL` and kills the value rule that the number itself would
// have fired. A mixed-script token carrying an ASCII digit is a tokenizer
// artifact, never an identifier: the identifiers the exception exists for
// ("p50", "ipv4") are ASCII by construction.
//
// Iterated by CODE POINT (`for…of`), not by code unit, so a non-BMP character
// counts once and never as a pair of lone surrogates.
function isTokenizerDigitArtifact(token: string): boolean {
  let hasDigit = false;
  let hasNonAscii = false;
  for (const ch of token) {
    const cp = ch.codePointAt(0) as number;
    if (cp >= 0x30 && cp <= 0x39) hasDigit = true;
    if (cp > 0x7f) hasNonAscii = true;
  }
  return hasDigit && hasNonAscii;
}

// Exactly the characters Python's `str.isspace()` accepts — see the header note.
const PY_SPACE = " \\t\\n\\v\\f\\r\\u001c-\\u001f\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";

// RE2-compatible: no lookaround, no backreferences, no backtracking. The
// letter-boundary check that RE2 would need lookbehind for is done in code
// below, precisely so this pattern ports unchanged. `g` is required for
// `matchAll`/`exec` iteration in JS; Python's `finditer` needs no such flag.
const NUMBER_RE = new RegExp(`([0-9][0-9,]*(?:\\.[0-9]+)?)[${PY_SPACE}]*([a-z]+|%)?`, "g");

// The letter-boundary guard is LATIN-ONLY, deliberately, and this is the one
// place the two facts have to be held together:
//
//   - the identifiers it protects are ASCII by construction — "p50", "p99",
//     "ipv4", "ipv6", "sec4", "http2". The text is already lowercased where the
//     check runs, so a–z covers every ASCII letter that can reach it, and the
//     digits it guards are the ASCII [0-9] the pattern itself matched;
//   - `\p{L}` (like Python's `str.isalpha()` and Go's `unicode.IsLetter`) is
//     also TRUE for kana, kanji and Han. Japanese and Chinese do not put spaces
//     around numbers, so in 「通知期間は30日です。」 the kana は sits flush against
//     the 3, the number was discarded as an "identifier", `numbers` came back
//     empty, and the value rule never ran. The SAME sentence with a non-letter
//     separator (「通知期間: 30日」) did fire — measured. Two of the world's
//     largest written languages were inert for the one conflict rule that is
//     otherwise script-independent, which is exactly the one-sided-answer
//     failure ADR-0007 exists to prevent.
//
// Narrowing to ASCII keeps every identifier case working (they are all ASCII)
// and lets CJK numbers parse. It also widens the value rule to any other script
// that writes a letter flush against a digit; that is the intended direction —
// the guard exists to protect ASCII identifiers, not to suppress non-Latin text.
// As a bonus it removes a JS-only hazard: `lowered[start - 1]` is a UTF-16 code
// UNIT, so for a non-BMP letter it was a lone surrogate that `\p{L}` failed
// anyway — the three ports were not in fact identical there.
const IDENTIFIER_PREFIX = /[a-z_]/;

const STOPWORDS: ReadonlySet<string> = new Set(STOPWORDS_TABLE);
const NEGATIONS: ReadonlySet<string> = new Set(CONFLICT_NEGATIONS_TABLE);
const MEASUREMENT_UNITS: ReadonlySet<string> = new Set(MEASUREMENT_UNITS_TABLE);
const REPORT_BIGRAMS: ReadonlySet<string> = new Set(
  CONFLICT_REPORT_BIGRAMS_TABLE.map(([a, b]) => `${a}\u0000${b}`),
);

/** The antonym table is stored in ONE direction; the reader symmetrises. */
const ANTONYMS: readonly (readonly [string, string])[] = CONFLICT_ANTONYMS_TABLE.flatMap(
  ([a, b]) => [
    [a, b] as const,
    [b, a] as const,
  ],
);

/**
 * Fold a regular English plural / third-person -s onto its base form.
 *
 * The pinned tokenizer (v2, ADR-0011) does **not** stem, and this does not
 * change it: folding happens inside the comparison only, and no other gate sees
 * it. Without it, morphology alone defeats the residual guard on true
 * contradictions that are otherwise word-identical — "requires"/"require",
 * "conserves"/"conserve", "attract"/"attracts" — each counting as a divergence
 * that is not a divergence.
 *
 * Deliberately one rule, not a stemmer: a single trailing `s`, never on short
 * tokens and never after `s`/`u`/`i` (`class`, `status`, `analysis`). A stemmer
 * would merge genuinely different words and every such merge is a false
 * conflict.
 */
export function fold(token: string): string {
  if (token.length >= 4 && token.endsWith("s") && !"siu".includes(token[token.length - 2] as string)) {
    return token.slice(0, -1);
  }
  return token;
}

const FOLDED_ANTONYMS: ReadonlySet<string> = new Set(
  ANTONYMS.map(([a, b]) => `${fold(a)}\u0000${fold(b)}`),
);
const FOLDED_SCOPE: ReadonlySet<string> = new Set(CONFLICT_SCOPE_MARKERS_TABLE.map(fold));

/** Everything the pairwise rules need from one passage. */
interface Features {
  tokens: readonly string[];
  /** folded, meaning-bearing, non-numeric, non-polarity */
  content: ReadonlySet<string>;
  negations: number;
  numbers: ReadonlySet<string>;
  units: ReadonlySet<string>;
  /** carries a reported-speech bigram */
  reported: boolean;
}

/** Why two passages were judged to disagree. Never says which one is right. */
export interface ConflictFinding {
  /** "antonym" | "negation" | "value" */
  rule: string;
  detail: string;
}

/** A detected conflict between two candidates, by position in the sequence. */
export interface ConflictPair {
  left: number;
  right: number;
  finding: ConflictFinding;
}

/** The one-line form written to `Result.conflicts`. */
export function describeConflictPair(
  pair: ConflictPair,
  leftDocument: string,
  rightDocument: string,
): string {
  return `${pair.finding.rule}: ${leftDocument} vs ${rightDocument} (${pair.finding.detail})`;
}

// ── set helpers (no Set.prototype.difference at ES2022 / Node 20) ───────────

function intersectionSize(a: ReadonlySet<string>, b: ReadonlySet<string>): number {
  let n = 0;
  for (const x of a) if (b.has(x)) n++;
  return n;
}

function difference(a: ReadonlySet<string>, b: ReadonlySet<string>): Set<string> {
  const out = new Set<string>();
  for (const x of a) if (!b.has(x)) out.add(x);
  return out;
}

/** `(a | b) - (a & b)` — the symmetric difference, spelled the way Python does. */
function divergenceOf(a: ReadonlySet<string>, b: ReadonlySet<string>): Set<string> {
  const out = new Set<string>();
  for (const x of a) if (!b.has(x)) out.add(x);
  for (const x of b) if (!a.has(x)) out.add(x);
  return out;
}

function setsEqual(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

/** `a <= b` — is every member of `a` also in `b`? */
function isSubset(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  if (a.size > b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

function sorted(values: Iterable<string>): string[] {
  return [...values].sort();
}

// ── number normalisation ───────────────────────────────────────────────────

/** Python's `str.rstrip(chars)`: strip EVERY trailing character in `chars`. */
function rstrip(value: string, chars: string): string {
  let end = value.length;
  while (end > 0 && chars.includes(value[end - 1] as string)) end--;
  return value.slice(0, end);
}

/**
 * String normalisation, never numeric parsing: `parseFloat` would lose
 * precision on long values and reformat exponents, and the result is a set key
 * compared for equality against Python's.
 */
function normalizeNumber(raw: string): string {
  let value = raw.replace(/,/g, "");
  if (value.includes(".")) {
    value = rstrip(rstrip(value, "0"), ".");
  }
  return value || "0";
}

function features(text: string): Features {
  const lowered = text.toLowerCase();
  const tokens = tokenizeV2(lowered);
  const numbers = new Set<string>();
  const units = new Set<string>();

  NUMBER_RE.lastIndex = 0;
  for (const match of lowered.matchAll(NUMBER_RE)) {
    // Group 1 begins at offset 0 of the match, so `match.index` IS `start(1)`.
    const start = match.index;
    const prev = start > 0 ? (lowered[start - 1] as string) : "";
    if (start > 0 && IDENTIFIER_PREFIX.test(prev)) {
      continue; // "p50", "ipv4": an identifier, not a measured value
    }
    numbers.add(normalizeNumber(match[1] as string));
    const unit = match[2];
    if (unit === "%") {
      units.add("%");
    } else if (unit !== undefined && unit !== "" && MEASUREMENT_UNITS.has(unit)) {
      units.add(unit);
    }
  }

  // Stopwords and negations are matched on the RAW token, before folding: the
  // fold is a comparison aid, not a normalizer, and folding first would turn
  // "does" into "doe" and smuggle a stopword into the content set.
  const content = new Set<string>();
  let negations = 0;
  for (const token of tokens) {
    if (NEGATIONS.has(token)) negations++;
    if (
      !STOPWORDS.has(token) &&
      !NEGATIONS.has(token) &&
      !MEASUREMENT_RE.test(token) &&
      !isTokenizerDigitArtifact(token)
    ) {
      content.add(fold(token));
    }
  }

  let reported = false;
  for (let i = 0; i < tokens.length - 1; i++) {
    if (REPORT_BIGRAMS.has(`${tokens[i] as string}\u0000${tokens[i + 1] as string}`)) {
      reported = true;
      break;
    }
  }

  return { tokens, content, negations, numbers, units, reported };
}

/**
 * Deterministic pairwise contradiction test. `null` means "no conflict".
 *
 * Pure and total: no model, no network, no I/O, no configuration. The guard
 * ORDER is load-bearing and matches the Python reference line for line.
 */
export function detectConflict(left: string, right: string): ConflictFinding | null {
  const a = features(left);
  const b = features(right);
  const minContent = Math.min(a.content.size, b.content.size);
  if (minContent < MIN_CONTENT) return null; // too short to compare honestly

  const overlap = intersectionSize(a.content, b.content) / minContent;
  if (overlap < SUBJECT_OVERLAP) return null; // not the same subject

  const divergence = divergenceOf(a.content, b.content);
  if (divergence.size > MAX_SYMDIFF) return null;

  for (const token of divergence) {
    // differently scoped -> complementary, not contradictory
    if (FOLDED_SCOPE.has(token)) return null;
  }

  if (a.reported || b.reported) return null; // a quoted negation belongs to a third party

  // `Set` iteration is INSERTION-ordered; Python iterates `sorted()`. Sorting
  // explicitly is what makes the FIRST hit — and therefore the detail string —
  // the same one Python reports.
  const onlyA = sorted(difference(a.content, b.content));
  const onlyB = sorted(difference(b.content, a.content));
  for (const x of onlyA) {
    for (const y of onlyB) {
      if (!FOLDED_ANTONYMS.has(`${x}\u0000${y}`)) continue;
      let residual = 0;
      for (const token of divergence) {
        if (token !== x && token !== y) residual++;
      }
      if (residual <= MAX_RESIDUAL) {
        return { rule: "antonym", detail: `${x} vs ${y}` };
      }
    }
  }

  // Parity, not presence: a double negative is an assertion.
  if (a.negations % 2 !== b.negations % 2 && divergence.size <= MAX_RESIDUAL) {
    return { rule: "negation", detail: `${a.negations} vs ${b.negations} negations` };
  }

  if (a.numbers.size > 0 && b.numbers.size > 0 && !setsEqual(a.numbers, b.numbers)) {
    const elaboration = isSubset(a.numbers, b.numbers) || isSubset(b.numbers, a.numbers);
    if (!elaboration && setsEqual(a.units, b.units) && divergence.size <= MAX_RESIDUAL) {
      return {
        rule: "value",
        detail: `${sorted(a.numbers).join(", ")} vs ${sorted(b.numbers).join(", ")}`,
      };
    }
  }

  return null;
}

/**
 * Collapse reason if the two are SURFACE CLONES, else `null`.
 *
 * This claims one thing and not another. It detects the same passage appearing
 * twice — identical token sequence, or a near-identical one of equal length,
 * equal numbers and equal negation parity. It does **not** measure evidential
 * independence, and cannot: "the same fact restated" and "the same source
 * paraphrased" are both semantic equivalence with lexical divergence, so a
 * textual detector sees one signal with two causes. What a caller actually
 * wants from `distinct_documents` is a fact about *provenance*, not text — two
 * independent auditors can write the same sentence, and one source can be
 * quoted in twenty documents in twenty phrasings.
 *
 * So it is biased to UNDER-collapse. A word-order paraphrase is left standing.
 * Under-collapsing leaves `distinct_documents` as inflated as it is today;
 * over-collapsing would under-report real corroboration, a new wrong signal.
 */
export function isNearDuplicate(left: string, right: string): string | null {
  if (detectConflict(left, right) !== null) {
    return null; // conflict first, always: a contradiction is never a clone
  }
  const leftTokens = tokenizeV2(left);
  const rightTokens = tokenizeV2(right);
  if (
    leftTokens.length === rightTokens.length &&
    leftTokens.every((t, i) => t === rightTokens[i])
  ) {
    return "exact"; // covers whitespace, punctuation and case variants
  }
  const a = features(left);
  const b = features(right);
  if (!setsEqual(a.numbers, b.numbers) || a.negations % 2 !== b.negations % 2) return null;

  const leftSet = new Set(leftTokens);
  const rightSet = new Set(rightTokens);
  const unionSize = new Set([...leftTokens, ...rightTokens]).size;
  if (unionSize === 0) return null;

  const jaccard = intersectionSize(leftSet, rightSet) / unionSize;
  if (
    jaccard >= DUPLICATE_JACCARD &&
    Math.abs(leftTokens.length - rightTokens.length) <= DUPLICATE_MAX_LENGTH_DELTA
  ) {
    // Python's `f"{jaccard:.2f}"`. The two formatters disagree only on an exact
    // binary tie at .xx5, and the only such value reachable at >= 0.80 is 0.875,
    // where both emit "0.88".
    return `near (${jaccard.toFixed(2)})`;
  }
  return null;
}

/** One line per conflict, naming both documents and neither as the winner. */
export function describeConflicts(
  pairs: readonly ConflictPair[],
  documents: readonly string[],
): string[] {
  return pairs.map((pair) =>
    describeConflictPair(pair, documents[pair.left] as string, documents[pair.right] as string),
  );
}

/** All conflicting pairs within the first `topK` passages. */
export function findConflicts(
  passages: readonly string[],
  topK: number = CONFLICT_TOP_K,
): ConflictPair[] {
  const window = passages.slice(0, topK);
  const pairs: ConflictPair[] = [];
  for (let i = 0; i < window.length; i++) {
    for (let j = i + 1; j < window.length; j++) {
      const finding = detectConflict(window[i] as string, window[j] as string);
      if (finding !== null) pairs.push({ left: i, right: j, finding });
    }
  }
  return pairs;
}

/** Indices of the passages that survive surface-clone collapse, in order. */
export function collapseNearDuplicates(passages: readonly string[]): number[] {
  const kept: number[] = [];
  for (let index = 0; index < passages.length; index++) {
    const text = passages[index] as string;
    const duplicate = kept.some((k) => isNearDuplicate(text, passages[k] as string) !== null);
    if (duplicate) continue;
    kept.push(index);
  }
  return kept;
}
