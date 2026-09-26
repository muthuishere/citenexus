// Bilingual qualifier pairs, bound to a number — port of
// golang/answer/verify_qualifier_pairs.go.
//
// A pair is a language-independent class (bruto/gross ⇄ netto/net). The claim's
// number binds to the nearest qualifier form within a small window in its
// clause; each unit clause holding the same number binds its own. Refused when
// no such unit clause carries the claim's side and at least one carries the
// other. Without a number nothing is compared.

import { findAllStrings, goLower, goQuote, goTrim } from "./gotext.js";
import { numbersIn } from "./numbers.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { anyForm } from "./verify-guards-model.js";
import { LIST_LEAD_TOKEN, ROLE_TRIM, roleClauses } from "./verify-roles.js";

/** Two opposite qualifiers, each with its forms in any language (lowercase). */
export interface QualifierPair {
  a: readonly string[];
  b: readonly string[];
}

/** gross/net, permanent/temporary contract, full/part time. */
export const DEFAULT_QUALIFIER_PAIRS: readonly QualifierPair[] = Object.freeze([
  { a: ["bruto", "gross"], b: ["netto", "net"] },
  { a: ["vast", "vaste", "permanent", "indefinite"], b: ["tijdelijk", "tijdelijke", "temporary"] },
  { a: ["voltijd", "voltijds", "fulltime", "full-time"], b: ["deeltijd", "deeltijds", "parttime", "part-time"] },
]);

const QUALIFIER_NUMBER_WINDOW = 3;

function sideNear(words: readonly string[], i: number, pair: QualifierPair): [number, string] {
  for (let d = 0; d <= QUALIFIER_NUMBER_WINDOW; d++) {
    for (const j of [i - d, i + d]) {
      if (j < 0 || j >= words.length) continue;
      const w = words[j] as string;
      const a = anyForm(w, pair.a);
      const b = anyForm(w, pair.b);
      if (a && !b) return [0, w];
      if (b && !a) return [1, w];
    }
  }
  return [-1, ""];
}

export function lowerWords(clause: string): string[] {
  return findAllStrings(LIST_LEAD_TOKEN, clause).map((w) => goLower(goTrim(w, ROLE_TRIM)));
}

/** Per word index, the ADR-0015 keys of its numbers. */
export function numberWordKeys(clause: string, language: string): Map<number, string[]> {
  const out = new Map<number, string[]>();
  findAllStrings(LIST_LEAD_TOKEN, clause).forEach((w, i) => {
    for (const m of numbersIn(w, language)) {
      const list = out.get(i);
      if (list === undefined) out.set(i, [m.reading.key]);
      else list.push(m.reading.key);
    }
  });
  return out;
}

/** qualifierPairGuard: see the file comment. */
export function qualifierPairGuard(
  claim: string,
  claimLanguage: string,
  eu: EvidenceUnit,
  pairs: readonly QualifierPair[],
): string {
  const unit = roleClauses(eu.text).map((c) => ({ words: lowerWords(c), keys: numberWordKeys(c, eu.language) }));
  for (const c of roleClauses(claim)) {
    const words = lowerWords(c);
    for (const [i, keys] of numberWordKeys(c, claimLanguage)) {
      for (const pair of pairs) {
        const [side, form] = sideNear(words, i, pair);
        if (side < 0) continue;
        let agrees = false;
        let other = "";
        for (const uc of unit) {
          for (const [j, ukeys] of uc.keys) {
            if (!sharesKey(keys, ukeys)) continue;
            if (clauseHasSide(uc.words, side, pair)) {
              agrees = true;
              continue;
            }
            const [us, uform] = sideNear(uc.words, j, pair);
            if (us >= 0 && us !== side && other === "") other = uform;
          }
        }
        if (!agrees && other !== "") {
          return `qualifier guard: the claim says ${goQuote(form)} where the passage says ${goQuote(other)}`;
        }
      }
    }
  }
  return "";
}

export function sharesKey(a: readonly string[], b: readonly string[]): boolean {
  return a.some((x) => b.includes(x));
}

function clauseHasSide(words: readonly string[], side: number, pair: QualifierPair): boolean {
  const forms = side === 1 ? pair.b : pair.a;
  return words.some((w) => anyForm(w, forms));
}
