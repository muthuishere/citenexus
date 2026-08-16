// ADR-0009 — ordered containment with a polarity guard.
//
// `isSupported` is set containment, and set containment is closed under two
// meaning-changing operations: reordering (inverting the parties to an
// obligation is a token-set identity) and deletion ("not" is a token, so
// dropping a negation yields a strict subset). Measured in
// spikes/library-stress/: nine false answers accepted 9/9, identically in
// Python, Go and JS.
//
// `isSupportedV2` requires the claim's tokens to appear IN ORDER within a
// bounded interior gap, and requires any polarity marker inside the matched span
// to survive into the claim. It is strictly narrower than `isSupported` —
// anything it accepts, the frozen predicate accepted — so it can only reduce
// what passes. `isSupported` itself stays byte-identical for the frozen
// SPEC-PORTS-v1 §4 vectors.
//
// ADR-0010 tier 1: native per port, not the Rust core. An integer dynamic
// programme over two token arrays, with NO regex anywhere in it.
//
// The polarity table is ADR-0010 tier 2 — shared data, per-port code. It is read
// from conformance/polarity.json, the single canonical definition, exactly as
// the stopword list already is. There is no hand-maintained copy.

import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { POLARITY_TABLE } from "../gen/tables.js";

/** Tokens whose DELETION flips the meaning of a claim (conformance/polarity.json,
 * bundled via scripts/gen-tables.mjs so the published package is self-contained). */
export const POLARITY_MARKERS: ReadonlySet<string> = new Set(POLARITY_TABLE.markers);

// Pinned, not configurable. A caller who widens the budget silently weakens the
// guarantee, and a conformance vector cannot pin a value the caller controls.
// The ADR-0009 spike swept the budget and found the knee at (3, 6); (4, 8)
// leaves headroom for compressed answers. The attacks are insensitive to it —
// they fail on order, not on gap size.
export const MAX_SINGLE_GAP = 4;
export const MAX_TOTAL_GAP = 8;

/** Where a claim matched inside a passage, in token indices. */
export interface Alignment {
  /** index of the first matched passage token */
  start: number;
  /** index of the last matched passage token (inclusive) */
  end: number;
  /** passage tokens skipped strictly inside the span */
  totalGap: number;
  /** the largest single skip inside the span */
  maxGap: number;
}

/** One DP state: the best (totalGap, maxGap, start) for a prefix ending here. */
interface Cell {
  total: number;
  max: number;
  start: number;
}

/**
 * Minimal-gap ordered alignment of `claimTokens` into `passageTokens`.
 *
 * Returns the alignment minimising total interior gap, or `null` when the claim
 * is not an order- and multiplicity-preserving subsequence of the passage within
 * the gap budget. O(claim * passage) integer DP — no regex, no recursion.
 */
export function align(
  claimTokens: readonly string[],
  passageTokens: readonly string[],
  maxSingleGap: number = MAX_SINGLE_GAP,
  maxTotalGap: number = MAX_TOTAL_GAP,
): Alignment | null {
  if (claimTokens.length === 0 || passageTokens.length === 0) return null;

  const n = claimTokens.length;
  const m = passageTokens.length;
  let state: (Cell | null)[] = new Array<Cell | null>(m).fill(null);

  // The claim's first token may start anywhere it occurs.
  for (let j = 0; j < m; j++) {
    if (passageTokens[j] === claimTokens[0]) state[j] = { total: 0, max: 0, start: j };
  }

  for (let i = 1; i < n; i++) {
    const next: (Cell | null)[] = new Array<Cell | null>(m).fill(null);
    let best: Cell | null = null; // running best over k < j
    let bestK = -1;
    for (let j = 0; j < m; j++) {
      // fold position j-1 into the running best before using it for j
      const prev = j > 0 ? (state[j - 1] ?? null) : null;
      if (prev !== null && (best === null || prev.total < best.total)) {
        best = prev;
        bestK = j - 1;
      }
      if (passageTokens[j] !== claimTokens[i] || best === null) continue;
      const gap = j - bestK - 1;
      if (gap > maxSingleGap) continue;
      const total = best.total + gap;
      if (total > maxTotalGap) continue;
      next[j] = { total, max: Math.max(best.max, gap), start: best.start };
    }
    state = next;
    if (state.every((s) => s === null)) return null;
  }

  // min over (totalGap, end index) — ties break to the leftmost end.
  let bestCell: Cell | null = null;
  let bestEnd = -1;
  for (let j = 0; j < m; j++) {
    const s = state[j] ?? null;
    if (s === null) continue;
    if (bestCell === null || s.total < bestCell.total) {
      bestCell = s;
      bestEnd = j;
    }
  }
  if (bestCell === null) return null;
  return { start: bestCell.start, end: bestEnd, totalGap: bestCell.total, maxGap: bestCell.max };
}

/**
 * Every polarity marker inside the matched span must survive into the claim.
 * Multiplicity matters: dropping one of two negations flips the meaning just as
 * completely as dropping the only one.
 */
function polarityPreserved(
  claimTokens: readonly string[],
  passageTokens: readonly string[],
  span: Alignment,
): boolean {
  const inSpan = new Map<string, number>();
  for (let j = span.start; j <= span.end; j++) {
    const tok = passageTokens[j] as string;
    if (POLARITY_MARKERS.has(tok)) inSpan.set(tok, (inSpan.get(tok) ?? 0) + 1);
  }
  if (inSpan.size === 0) return true;

  const inClaim = new Map<string, number>();
  for (const tok of claimTokens) {
    if (inSpan.has(tok)) inClaim.set(tok, (inClaim.get(tok) ?? 0) + 1);
  }
  for (const [tok, want] of inSpan) {
    if ((inClaim.get(tok) ?? 0) < want) return false;
  }
  return true;
}

/**
 * Order- and multiplicity-aware containment plus the polarity guard (ADR-0009).
 * Pure, deterministic, offline. Strictly narrower than `isSupported`.
 */
export function isSupportedV2(answer: string, passage: string): boolean {
  const claimTokens = tokenizeV2(answer);
  const passageTokens = tokenizeV2(passage);
  const span = align(claimTokens, passageTokens);
  if (span === null) return false;
  return polarityPreserved(claimTokens, passageTokens, span);
}
