// The union rule for a list item joined to a content lead-in — port of
// golang/answer/verify_union.go.
//
// The writer often cites the lead-in to the unit that NAMES the provision and
// the item to the unit that STATES the fact. The union rule admits such a claim
// against the lead-in's unit A and the item's unit B together — only the
// lead-in's REFERENCES may come from A; guards run split by provenance; the
// model must entail the joined claim from A+B. Never on the gate path.

import { POLARITY_MARKERS } from "../gate/verify-v2.js";
import { isStopword } from "../gate/gate.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { containsAny, findAllStrings, goLower, goQuote, goTrim } from "./gotext.js";
import { LIST_REFERENCE_NOUNS, primaryLanguage } from "./verify-answer.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { guards, names } from "./verify-guards.js";
import type { GuardConfig } from "./verify-guards.js";
import { CONTEXT_STOP } from "./verify-guards-model.js";
import { LIST_LEAD_TOKEN } from "./verify-roles.js";

/** The evidence a joined item is checked against: the lead-in's unit, then the
 * item's. Two languages that differ leave it undeclared. */
export function unionPremise(a: EvidenceUnit, b: EvidenceUnit): EvidenceUnit {
  let language = a.language;
  if (primaryLanguage(a.language) !== primaryLanguage(b.language)) language = "";
  return {
    id: a.id + "\u0000" + b.id,
    documentId: a.documentId + "\n" + b.documentId,
    text: a.text + "\n\n" + b.text,
    language,
  };
}

/** The deterministic part of the union rule for one (A, B) pair: the first refusal, or "". */
export function unionRefusal(
  claim: string,
  lead: string,
  item: string,
  claimLanguage: string,
  a: EvidenceUnit,
  b: EvidenceUnit,
  cfg: GuardConfig,
): string {
  let reason = leadInScope(lead, b);
  if (reason !== "") return reason;
  reason = guards(lead, claimLanguage, a, { ...cfg, fragment: true });
  if (reason !== "") return reason;
  reason = guards(item, claimLanguage, b, cfg);
  if (reason !== "") return reason;
  return guards(claim, claimLanguage, unionPremise(a, b), cfg);
}

const LEAD_IN_ATTRIBUTION: ReadonlySet<string> = new Set([
  "volgens", "krachtens", "ingevolge", "conform", "onder",
  "geldt", "gelden", "bepaalt",
  "according", "pursuant", "under", "applies", "apply",
  "provides", "states",
]);

/** Every word of the lead-in that is not a reference must be in the item's unit B. */
function leadInScope(lead: string, b: EvidenceUnit): string {
  const have = new Set(tokenizeV2(b.text));
  const named = new Set<string>();
  for (const name of names(lead)) for (const tok of tokenizeV2(name)) named.add(tok);
  const words = findAllStrings(LIST_LEAD_TOKEN, lead);
  const reference: boolean[] = new Array<boolean>(words.length).fill(false);
  words.forEach((w, i) => {
    if (!LIST_REFERENCE_NOUNS.has(goLower(goTrim(w, ".,;:()[]\"'")))) return;
    reference[i] = true;
    if (i + 1 < words.length && containsAny(words[i + 1] as string, "0123456789")) reference[i + 1] = true;
  });
  for (let i = 0; i < words.length; i++) {
    if (reference[i]) continue;
    for (const tok of tokenizeV2(words[i] as string)) {
      if (have.has(tok)) continue;
      if (!POLARITY_MARKERS.has(tok) && freeLeadInToken(tok, named)) continue;
      return `lead-in guard: ${goQuote(tok)} is not in the item's evidence`;
    }
  }
  return "";
}

function freeLeadInToken(tok: string, named: ReadonlySet<string>): boolean {
  if (isStopword(tok)) return true;
  return CONTEXT_STOP.has(tok) || LEAD_IN_ATTRIBUTION.has(tok) || named.has(tok);
}
