// The definition guard: a claim that uses the generic noun for a subtype the
// unit DEFINES explicitly — port of golang/answer/verify_definitions.go.
//
// Only EXPLICIT definitions are read: "<qualifier> <noun> (hierna: het <Term>)",
// "(hereinafter …)", "…, hierna 'Term'", "Onder <qualifier> <noun> wordt
// verstaan". A definition governs every unit of its document that uses the
// defined Term. On by default. Can only refuse.

import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { GS, findAll, findAllStrings, goLower, goQuote, goSplit, goTrim } from "./gotext.js";
import { primaryLanguage } from "./verify-answer.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { Carrier } from "./verify-conditions.js";
import type { GuardConfig } from "./verify-guards.js";
import { softJoin } from "./verify-guards-model.js";
import { partyWord, sentenceBreak } from "./verify-parties.js";
import { LIST_LEAD_TOKEN } from "./verify-roles.js";
import { glossEmpty, glossIdx } from "./glossary.js";

const S = `[${GS}]`;
const DEFINED_AFTER = new RegExp(
  `(\\p{L}+)${S}+(\\p{L}+)${S}*\\(${S}*(?:hierna(?:${S}+te${S}+noemen)?|hereinafter(?:${S}+referred${S}+to${S}+as)?)${S}*[:,]?${S}*(?:het|de|the)?${S}*['‘"“]?(\\p{L}+)['’"”]?${S}*\\)`,
  "dgu",
);
const DEFINED_QUOTE = new RegExp(`(\\p{L}+)${S}+(\\p{L}+)${S}*,?${S}*hierna${S}+['‘"“](\\p{L}+)['’"”]`, "dgu");
// (?i) in Go: Unicode simple case folding; ASCII keywords, \p{L} groups.
const DEFINED_UNDER = new RegExp(`\\bonder${S}+(\\p{L}+)${S}+(\\p{L}+)${S}+wordt${S}+verstaan`, "dgiu");

export interface Definition {
  qualifier: string;
  noun: string;
  term: string;
}

export function definitionsIn(text: string): Definition[] {
  const out: Definition[] = [];
  for (const re of [DEFINED_AFTER, DEFINED_QUOTE]) {
    for (const m of findAll(re, text)) {
      const q = goLower(m.group(1) as string);
      const n = goLower(m.group(2) as string);
      const term = m.group(3) as string;
      if (goLower(term) !== n || !partyWord(q)) continue;
      out.push({ qualifier: q, noun: n, term });
    }
  }
  for (const m of findAll(DEFINED_UNDER, text)) {
    if (partyWord(goLower(m.group(1) as string))) {
      out.push({ qualifier: goLower(m.group(1) as string), noun: goLower(m.group(2) as string), term: "" });
    }
  }
  return out;
}

function sameDef(a: Definition, b: Definition): boolean {
  return a.qualifier === b.qualifier && a.noun === b.noun && a.term === b.term;
}

function containsDef(defs: readonly Definition[], d: Definition): boolean {
  return defs.some((x) => sameDef(x, d));
}

/** definitionGuard: see the file comment. */
export function definitionGuard(claim: string, claimLanguage: string, eu: EvidenceUnit, cfg: GuardConfig): string {
  if (cfg.noDefinitions) return "";
  const defs = definitionsIn(eu.text);
  if (eu.documentId !== "") {
    for (const d of cfg.docDefs.get(eu.documentId) ?? []) {
      if (containsDef(defs, d)) continue;
      if (
        (d.term !== "" && writtenTerm(eu.text, d.term)) ||
        (d.term === "" && goLower(eu.text).includes(d.qualifier + " " + d.noun))
      ) {
        defs.push(d);
      }
    }
  }
  if (defs.length === 0) return "";
  const cross =
    claimLanguage !== "" && eu.language !== "" && primaryLanguage(claimLanguage) !== primaryLanguage(eu.language);
  if (cross && glossEmpty(cfg.gloss)) return "";
  const c = new Carrier(new Set(tokenizeV2(claim)), cross, glossIdx(cfg.gloss));
  const words = findAllStrings(LIST_LEAD_TOKEN, claim);
  for (const d of defs) {
    const [hasNoun, nounKnown] = c.carried(d.noun);
    if (!nounKnown || !hasNoun) continue;
    const [hasQual, qualKnown] = c.carried(d.qualifier);
    if (!qualKnown || hasQual) continue;
    if (d.term !== "") {
      let written = false;
      words.forEach((w, i) => {
        if (i > 0 && goTrim(w, ".,;:!?\"'()") === d.term) written = true;
      });
      if (written) continue;
    }
    return `definition guard: the passage defines ${goQuote(d.noun)} as ${goQuote(d.qualifier + " " + d.noun)}`;
  }
  return "";
}

/** The Term as written, not as the first word of a sentence. */
function writtenTerm(text: string, term: string): boolean {
  for (const s of goSplit(sentenceBreak, softJoin(text))) {
    const words = findAllStrings(LIST_LEAD_TOKEN, s);
    for (let i = 1; i < words.length; i++) if (goTrim(words[i] as string, ".,;:!?\"'()") === term) return true;
  }
  return false;
}

/** The explicit definitions of every unit, by document. */
export function documentDefinitions(evidence: readonly EvidenceUnit[]): Map<string, Definition[]> {
  const out = new Map<string, Definition[]>();
  for (const eu of evidence) {
    if (eu.documentId === "") continue;
    for (const d of definitionsIn(eu.text)) {
      const list = out.get(eu.documentId) ?? [];
      if (!containsDef(list, d)) list.push(d);
      out.set(eu.documentId, list);
    }
  }
  return out;
}
