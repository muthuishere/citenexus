// ADR-0011 — the Unicode tokenizer, v2.
//
// v1 (`tokenize`) is the frozen SPEC-PORTS-v1 §4 tokenizer: lowercase then
// [a-z0-9]+. That is ASCII only, which turned out to be a false capability claim
// rather than a limitation — Japanese, Chinese, Arabic and Tamil each produced
// ZERO tokens, so the faithfulness gate rejected a verbatim quote of its own
// source and BM25 scored nothing. v2 fixes that without touching v1: v1 stays
// exported and byte-identical, because the shipped conformance vectors and every
// index already built pin it.
//
// v2 is a strict superset of v1 on pure-ASCII input, which is why moving BM25
// and the gate onto it left every existing vector unchanged.
//
// PLACEMENT — ADR-0011 §3: tier 3 for AUTHORSHIP (the Rust core is authoritative
// and generates the conformance vectors) but tier 1 for DELIVERY. JS keeps a
// NATIVE-FREE implementation that those vectors pin; the tokenizer is the
// hottest path there is, and ADR-0010 forbids handing it a mandatory native/FFI
// dependency. Importing this module pulls in nothing.
//
// NO PATTERN MATCHING. This is a code-point scan over category and script
// tables, not a regex over the text, because Python `re` has no \p{L} and Go RE2
// and JS RegExp disagree on Unicode property escapes in ways no practical
// fixture set would catch. The single `RegExp` below is used only as a
// per-code-point general-category predicate — the exact counterpart of Go's
// `unicode.IsLetter || IsNumber || In(unicode.M)` — so the divergence risk is
// Unicode *version* skew between runtimes, which is what the conformance vectors
// exist to catch, not pattern semantics.

import { CASEFOLD_OVERRIDES } from "./casefold-table.js";
import { CONTINUOUS_SCRIPTS_TABLE, SUPPORTED_SCRIPTS_TABLE } from "../gen/tables.js";

/** Stamped on an index so a tokenizer/index mismatch is detectable rather than
 * silent (ADR-0011). Bump whenever `tokenizeV2`'s output changes for any input. */
export const TOKENIZER_VERSION = 2;

/** Scripts CiteNexus CLAIMS. ADR-0011: a script enters this set only when a
 * golden fixture proves it end-to-end. Everything else is reported by
 * `unsupportedScripts` so the caller gets a capability signal instead of the
 * evidence-absent refusal. */
export const SUPPORTED_SCRIPTS: ReadonlySet<string> = new Set(SUPPORTED_SCRIPTS_TABLE);

/** Scripts written without spaces between words; these are character-bigram
 * indexed. Korean is NOT here — Hangul writes spaces, so bigramming it would be
 * a regression. */
export const CONTINUOUS_SCRIPTS: ReadonlySet<string> = new Set(CONTINUOUS_SCRIPTS_TABLE);

// (first, last, script) — MUST stay sorted and disjoint; the binary search
// depends on it and a mis-sorted table would silently mis-classify. Python's
// stdlib has no Script property either, so the ranges are carried explicitly in
// every port; the behavioural conformance vectors are what pin them. The table
// is deliberately partial: it covers the scripts CiteNexus makes a claim about
// plus the near neighbours it must be able to NAME when refusing.
const SCRIPT_RANGES: ReadonlyArray<readonly [number, number, string]> = [
  [0x0041, 0x005a, "latin"],
  [0x0061, 0x007a, "latin"],
  [0x00aa, 0x00aa, "latin"],
  [0x00ba, 0x00ba, "latin"],
  [0x00c0, 0x02af, "latin"],
  [0x0300, 0x036f, "common"], // combining diacriticals — inherit their base
  [0x0370, 0x03ff, "greek"],
  [0x0400, 0x052f, "cyrillic"],
  [0x0531, 0x058f, "armenian"],
  [0x0591, 0x05f4, "hebrew"],
  [0x0600, 0x06ff, "arabic"],
  [0x0750, 0x077f, "arabic"],
  [0x0870, 0x08ff, "arabic"],
  [0x0900, 0x097f, "devanagari"],
  [0x0980, 0x09ff, "bengali"],
  [0x0b80, 0x0bff, "tamil"],
  [0x0e00, 0x0e7f, "thai"],
  [0x0e80, 0x0eff, "lao"],
  [0x1000, 0x109f, "myanmar"],
  [0x10a0, 0x10ff, "georgian"],
  [0x1100, 0x11ff, "hangul"],
  [0x1780, 0x17ff, "khmer"],
  [0x1e00, 0x1eff, "latin"],
  [0x1f00, 0x1fff, "greek"],
  [0x2c60, 0x2c7f, "latin"],
  [0x2de0, 0x2dff, "cyrillic"],
  [0x2e80, 0x2eff, "han"],
  [0x3005, 0x3007, "han"],
  [0x3040, 0x309f, "hiragana"],
  [0x30a0, 0x30ff, "katakana"],
  [0x3130, 0x318f, "hangul"],
  [0x31f0, 0x31ff, "katakana"],
  [0x3400, 0x4dbf, "han"],
  [0x4e00, 0x9fff, "han"],
  [0xa640, 0xa69f, "cyrillic"],
  [0xa720, 0xa7ff, "latin"],
  [0xa960, 0xa97f, "hangul"],
  [0xac00, 0xd7a3, "hangul"],
  [0xf900, 0xfaff, "han"],
  [0xfb1d, 0xfb4f, "hebrew"],
  [0xfb50, 0xfdff, "arabic"],
  [0xfe70, 0xfeff, "arabic"],
  [0xff21, 0xff3a, "latin"],
  [0xff41, 0xff5a, "latin"],
  [0x20000, 0x2a6df, "han"],
];

/** Exported for the drift-guard test that asserts the table stays sorted. */
export const SCRIPT_RANGES_FOR_TEST = SCRIPT_RANGES;

/**
 * The script of one character; `"common"` for script-neutral characters (digits,
 * combining diacriticals) and `"unknown"` for anything the table does not cover.
 *
 * Binary search over the sorted range table — no property escapes.
 */
export function scriptOf(ch: string): string {
  const cp = ch.codePointAt(0) ?? 0;
  if (cp >= 0x30 && cp <= 0x39) return "common";
  let lo = 0;
  let hi = SCRIPT_RANGES.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const [first, last, name] = SCRIPT_RANGES[mid]!;
    if (cp < first) hi = mid - 1;
    else if (cp > last) lo = mid + 1;
    else return name;
  }
  return "unknown";
}

// Letters, numbers and marks (general categories L, N, M) are word-forming;
// everything else separates. Anchored, single-code-point — a predicate, not a
// scan (see the header note).
const WORD_CHAR_RE = /^[\p{L}\p{N}\p{M}]$/u;

function isWordChar(ch: string): boolean {
  return WORD_CHAR_RE.test(ch);
}

/**
 * Python `str.casefold`, reproduced code point by code point.
 *
 * JS `toLowerCase` is not full case folding, so the overrides table carries
 * every code point where the two disagree (`ß` → `ss`, `ς` → `σ`, …).
 */
export function caseFold(text: string): string {
  let out = "";
  // Array-of-code-points iteration: `for…of` over a string yields whole code
  // points, never UTF-16 halves.
  for (const ch of text) {
    const cp = ch.codePointAt(0)!;
    out += CASEFOLD_OVERRIDES.get(cp) ?? ch.toLowerCase();
  }
  return out;
}

// Flush one same-script run into `out`.
function emit(run: string[], script: string, out: string[]): void {
  if (run.length === 0) return;
  if (CONTINUOUS_SCRIPTS.has(script) && run.length > 1) {
    // Character bigrams (Lucene CJKBigramFilter semantics). Deterministic,
    // dictionary-free, adequate for both lexical retrieval and ordered
    // containment. Bigrams never cross a script boundary, because a boundary
    // ends the run before this is called.
    for (let i = 0; i < run.length - 1; i += 1) out.push(run[i]! + run[i + 1]!);
    return;
  }
  out.push(run.join(""));
}

/**
 * Unicode-aware tokenization with bigram segmentation for spaceless scripts.
 *
 * NFKC-normalized and case-folded, then scanned into maximal same-script runs of
 * word characters. Runs in a continuous script become character bigrams; all
 * others become one token each. Parity with the Python reference
 * `citenexus.tokenize.tokenize_v2`.
 */
export function tokenizeV2(text: string): string[] {
  // casefold can denormalize, so normalize once more afterwards. Idempotent for
  // the overwhelming majority of input.
  const normalized = caseFold(text.normalize("NFKC")).normalize("NFKC");

  const out: string[] = [];
  let run: string[] = [];
  let runScript = "common";
  // Array.from, not indexing: UTF-16 code-unit indices would split astral
  // characters (the 0x20000 Han range) in half.
  for (const ch of Array.from(normalized)) {
    if (!isWordChar(ch)) {
      emit(run, runScript, out);
      run = [];
      runScript = "common";
      continue;
    }
    const script = scriptOf(ch);
    if (run.length > 0 && script !== "common" && runScript !== "common" && script !== runScript) {
      // A script boundary inside a run of word characters ("東京tokyo").
      emit(run, runScript, out);
      run = [];
      runScript = "common";
    }
    run.push(ch);
    if (runScript === "common") runScript = script;
  }
  emit(run, runScript, out);
  return out;
}

/** Every script present in `text`'s word characters, sorted, without `"common"`
 * — digits and punctuation carry no script claim. */
export function scriptsIn(text: string): string[] {
  const found = new Set<string>();
  for (const ch of Array.from(text)) {
    if (isWordChar(ch)) found.add(scriptOf(ch));
  }
  found.delete("common");
  return [...found].sort();
}

/**
 * The scripts in `text` that CiteNexus does not claim to support.
 *
 * A non-empty result is a **capability** signal, not an evidence judgement.
 * Returning the evidence-absent refusal for a capability gap is the specific
 * thing that let the ASCII-only tokenizer hide for as long as it did.
 */
export function unsupportedScripts(text: string): string[] {
  return scriptsIn(text).filter((s) => !SUPPORTED_SCRIPTS.has(s));
}
