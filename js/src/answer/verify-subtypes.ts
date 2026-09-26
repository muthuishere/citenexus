// The subtype guard: the bare head noun for a fact the unit states only of a
// subtype — port of golang/answer/verify_subtypes.go. For a small class of head
// nouns (leave, allowance, reimbursement, benefit), a claim using the head BARE
// over a unit where the head occurs only as the head of compounds or behind a
// known scope qualifier is refused. Can only refuse.

import { isStopword } from "../gate/gate.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { byteLen, goQuote } from "./gotext.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { SCOPE_QUALIFIERS, hasTerm, isContextStop } from "./verify-conditions.js";
import { GROUP_PREPOSITIONS } from "./verify-exclusions.js";
import type { GuardConfig } from "./verify-guards.js";
import { numberValue, unitOf } from "./verify-guards-model.js";
import { isArticle } from "./verify-roles.js";

/** One head noun with its forms in any language (lowercase). */
export interface SubtypeHead {
  forms: readonly string[];
}

/** leave, allowance, reimbursement, benefit. */
export const DEFAULT_SUBTYPE_HEADS: readonly SubtypeHead[] = Object.freeze([
  { forms: ["verlof", "leave"] },
  { forms: ["toelage", "toelagen", "allowance", "allowances"] },
  { forms: ["vergoeding", "vergoedingen", "reimbursement", "reimbursements"] },
  { forms: ["uitkering", "uitkeringen", "benefit", "benefits"] },
]);

/** tokens[i] is a head form used without a modifier before it. */
function bareUse(tokens: readonly string[], i: number): boolean {
  if (i === 0) return true;
  const prev = tokens[i - 1] as string;
  if (isStopword(prev) || isContextStop(prev) || isArticle(prev)) return true;
  if (numberValue(prev, "")[1]) return true;
  if (unitOf(prev)[2]) return true;
  if (GROUP_PREPOSITIONS.has(prev)) return true;
  switch (prev) {
    case "tijdens":
    case "during":
    case "bij":
    case "voor":
    case "for":
    case "zonder":
    case "without":
    case "geen":
    case "no":
      return true;
  }
  return false;
}

/** subtypeGuard: see the file comment. */
export function subtypeGuard(claim: string, eu: EvidenceUnit, cfg: GuardConfig): string {
  const claimTokens = tokenizeV2(claim);
  const unitTokens = tokenizeV2(eu.text);
  for (const head of cfg.subtypes) {
    let claimBare = "";
    claimTokens.forEach((t, i) => {
      if (hasTerm(head.forms, t) && bareUse(claimTokens, i)) claimBare = t;
    });
    if (claimBare === "") continue;
    let bare = false;
    let qualified = false;
    let example = "";
    for (let i = 0; i < unitTokens.length; i++) {
      const t = unitTokens[i] as string;
      if (hasTerm(head.forms, t)) {
        if (i > 0 && SCOPE_QUALIFIERS.has(unitTokens[i - 1] as string)) {
          qualified = true;
          example = (unitTokens[i - 1] as string) + " " + t;
          continue;
        }
        bare = true;
        continue;
      }
      for (const f of head.forms) {
        if (byteLen(t) > byteLen(f) + 2 && t.endsWith(f)) {
          qualified = true;
          example = t;
        }
      }
    }
    if (qualified && !bare) {
      return `subtype guard: the claim says ${goQuote(claimBare)}; the passage only speaks of ${goQuote(example)}`;
    }
  }
  return "";
}
