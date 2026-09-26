// The verb guard: two distinct acts on the same object — port of
// golang/answer/verify_verbpairs.go. Applying for leave and taking it are
// different acts; the model reads them as one. Refused when a unit clause
// sharing an object word has the other act and the unit never states the
// claim's act. Across languages only through the glossary. Can only refuse.

import { isStopword } from "../gate/gate.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { goQuote, runeLen } from "./gotext.js";
import { primaryLanguage } from "./verify-answer.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { Carrier, isContextStop } from "./verify-conditions.js";
import type { GuardConfig } from "./verify-guards.js";
import { roleClauses } from "./verify-roles.js";
import { glossEmpty, glossIdx } from "./glossary.js";

/** Two distinct acts, each with its forms in any language (lowercase;
 * "verb+particle" for a Dutch separable verb). */
export interface VerbPair {
  a: readonly string[];
  b: readonly string[];
}

/** Applying for something and taking or using it. */
export const DEFAULT_VERB_PAIRS: readonly VerbPair[] = Object.freeze([
  {
    a: ["aanvragen", "aanvraagt", "aangevraagd", "aanvraag", "aanvragen", "application", "vraagt+aan", "vraag+aan", "vragen+aan", "apply", "applies", "applied", "request", "requests", "requested"],
    b: ["opnemen", "opneemt", "opgenomen", "opname", "opnames", "neemt+op", "neem+op", "nemen+op", "take", "takes", "taken", "took", "use", "uses", "used"],
  },
]);

/** [0 (A) | 1 (B) | -1 none or both, the matched tokens' positions]. */
function sideIn(tokens: readonly string[], pair: VerbPair): [number, Set<number>] {
  const hit = (forms: readonly string[]): Set<number> => {
    const at = new Set<number>();
    for (const f of forms) {
      const plus = f.indexOf("+");
      const verb = plus < 0 ? f : f.slice(0, plus);
      const particle = plus < 0 ? "" : f.slice(plus + 1);
      for (let i = 0; i < tokens.length; i++) {
        if (tokens[i] !== verb) continue;
        if (plus < 0) {
          at.add(i);
          continue;
        }
        for (let k = i + 1; k < tokens.length; k++) {
          if (tokens[k] === particle) {
            at.add(i);
            at.add(k);
            break;
          }
        }
      }
    }
    return at;
  };
  const a = hit(pair.a);
  const b = hit(pair.b);
  if (a.size > 0 && b.size === 0) return [0, a];
  if (b.size > 0 && a.size === 0) return [1, b];
  return [-1, new Set()];
}

/** verbPairGuard: see the file comment. */
export function verbPairGuard(
  claim: string,
  claimLanguage: string,
  eu: EvidenceUnit,
  pairs: readonly VerbPair[],
  cfg: GuardConfig,
): string {
  const cross =
    claimLanguage !== "" && eu.language !== "" && primaryLanguage(claimLanguage) !== primaryLanguage(eu.language);
  if (cross && glossEmpty(cfg.gloss)) return "";
  for (const pair of pairs) {
    for (const cc of roleClauses(claim)) {
      const ct = tokenizeV2(cc);
      const [side, verbAt] = sideIn(ct, pair);
      if (side < 0) continue;
      const claimSet = new Set<string>();
      ct.forEach((t, i) => {
        if (!verbAt.has(i)) claimSet.add(t);
      });
      const c = new Carrier(claimSet, cross, glossIdx(cfg.gloss));
      let agrees = false;
      let other = "";
      for (const uc of roleClauses(eu.text)) {
        const ut = tokenizeV2(uc);
        const [us, uAt] = sideIn(ut, pair);
        if (us < 0) continue;
        if (us === side) {
          agrees = true;
          continue;
        }
        let shared = false;
        for (let i = 0; i < ut.length; i++) {
          const t = ut[i] as string;
          if (uAt.has(i) || isStopword(t) || isContextStop(t) || runeLen(t) < 4) continue;
          if (c.carried(t)[0]) {
            shared = true;
            break;
          }
        }
        if (!shared) continue;
        if (other === "") {
          for (let i = 0; i < ut.length; i++) {
            if (uAt.has(i)) {
              other = ut[i] as string;
              break;
            }
          }
        }
      }
      if (!agrees && other !== "") {
        let claimVerb = "";
        for (let i = 0; i < ct.length; i++) {
          if (verbAt.has(i)) {
            claimVerb = ct[i] as string;
            break;
          }
        }
        return `verb guard: the claim says ${goQuote(claimVerb)} where the passage says ${goQuote(other)}`;
      }
    }
  }
  return "";
}
