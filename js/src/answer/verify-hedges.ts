// The hedge guard: a claim that states absolutely what the source hedges or
// limits — port of golang/answer/verify_hedges.go.
//
//   - ABSOLUTE ADDED: the claim carries an absolutizer and the unit none.
//   - HEDGE DROPPED: the unit sentence the claim follows attaches a hedge
//     (permission, upper bound, softener) and the claim carries none of that
//     class. Can only refuse.

import { POLARITY_MARKERS } from "../gate/verify-v2.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { GS, goLower, goQuote, goSplit, matches } from "./gotext.js";
import { numbersIn, verbatimIn } from "./numbers.js";
import { primaryLanguage } from "./verify-answer.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { Carrier, conditionContent } from "./verify-conditions.js";
import { BOUND_UPPER, splitBounds } from "./verify-guards.js";
import type { GuardConfig } from "./verify-guards.js";
import { softJoin } from "./verify-guards-model.js";
import { findSpans, sentenceBreak } from "./verify-parties.js";
import type { Span } from "./verify-parties.js";
import { glossIdx } from "./glossary.js";

const ABSOLUTIZERS: readonly (readonly string[])[] = [
  ["altijd"], ["always"], ["steeds"], ["te", "allen", "tijde"], ["at", "all", "times"], ["voortdurend"],
  ["at", "any", "time"], ["op", "elk", "moment"], ["whenever"],
  ["wanneer", "ze", "maar", "willen"], ["without", "restriction"], ["zonder", "beperking"],
  ["for", "any", "reason"], ["om", "welke", "reden", "dan", "ook"], ["ongeacht"], ["regardless"],
  ["in", "alle", "gevallen"], ["in", "all", "cases"], ["for", "as", "long", "as", "needed"],
  ["zo", "lang", "als", "nodig"], ["at", "all"], ["onbeperkt"], ["unlimited"],
];

const HEDGE_PERMISSION = "permission";
const HEDGE_UPPER = "upper bound";
const HEDGE_SOFTENER = "softener";

interface Phrase {
  words: readonly string[];
  cls: string;
}

const HEDGE_PHRASES: readonly Phrase[] = [
  { words: ["mag"], cls: HEDGE_PERMISSION }, { words: ["mogen"], cls: HEDGE_PERMISSION }, { words: ["kan"], cls: HEDGE_PERMISSION },
  { words: ["kunnen"], cls: HEDGE_PERMISSION }, { words: ["kun"], cls: HEDGE_PERMISSION }, { words: ["kunt"], cls: HEDGE_PERMISSION },
  { words: ["may"], cls: HEDGE_PERMISSION }, { words: ["can"], cls: HEDGE_PERMISSION }, { words: ["might"], cls: HEDGE_PERMISSION },
  { words: ["maximaal"], cls: HEDGE_UPPER }, { words: ["ten", "hoogste"], cls: HEDGE_UPPER }, { words: ["hooguit"], cls: HEDGE_UPPER },
  { words: ["tot", "een", "maximum"], cls: HEDGE_UPPER }, { words: ["maximum"], cls: HEDGE_UPPER }, { words: ["up", "to"], cls: HEDGE_UPPER },
  { words: ["at", "most"], cls: HEDGE_UPPER }, { words: ["no", "more", "than"], cls: HEDGE_UPPER }, { words: ["capped"], cls: HEDGE_UPPER },
  { words: ["in", "beginsel"], cls: HEDGE_SOFTENER }, { words: ["in", "principe"], cls: HEDGE_SOFTENER },
  { words: ["in", "de", "regel"], cls: HEDGE_SOFTENER }, { words: ["zoveel", "mogelijk"], cls: HEDGE_SOFTENER },
  { words: ["in", "principle"], cls: HEDGE_SOFTENER }, { words: ["as", "a", "rule"], cls: HEDGE_SOFTENER },
  { words: ["as", "far", "as", "possible"], cls: HEDGE_SOFTENER }, { words: ["as", "much", "as", "possible"], cls: HEDGE_SOFTENER },
];

/** The hedge classes in tokens (class -> the words that carry it). */
export function hedgesIn(tokensIn: readonly string[], text: string): Map<string, string> {
  const out = new Map<string, string>();
  let tokens = tokensIn;
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i] as string;
    if (
      t === "zodat" ||
      t === "opdat" ||
      (t === "so" && i + 1 < tokens.length && tokens[i + 1] === "that") ||
      (t === "in" && i + 2 < tokens.length && tokens[i + 1] === "order" && tokens[i + 2] === "to")
    ) {
      tokens = tokens.slice(0, i);
      break;
    }
  }
  const boundMarker = new Set<number>();
  for (const b of splitBounds(tokens)) {
    boundMarker.add(b.marker);
    if (b.direction === BOUND_UPPER && !out.has(HEDGE_UPPER)) {
      out.set(HEDGE_UPPER, (tokens[b.marker] as string) + " … " + "than");
    }
  }
  for (const h of HEDGE_PHRASES) {
    for (const sp of findSpans(tokens, h.words)) {
      if (h.cls === HEDGE_PERMISSION) {
        let negated = false;
        for (let k = sp.end; k < tokens.length && k <= sp.end + 4; k++) {
          if (POLARITY_MARKERS.has(tokens[k] as string) && !boundMarker.has(k)) negated = true;
        }
        if (negated) continue;
      }
      if (!out.has(h.cls)) out.set(h.cls, h.words.join(" "));
    }
  }
  if (matches(TOT_AMOUNT, goLower(text)) && !out.has(HEDGE_UPPER)) out.set(HEDGE_UPPER, "tot");
  return out;
}

const CLAIM_RANGE = new RegExp(
  `\\b[0-9][0-9.,]*[${GS}]*(?:tot|to|t/m|-|–)[${GS}]*[0-9]|\\b(?:tussen|between)[${GS}]+[0-9][0-9.,]*[${GS}]+(?:en|and)[${GS}]+[0-9]`,
  "dgu",
);
const TO_SAME_AMOUNT = new RegExp(`\\b(?:to|tot)[${GS}]*(?:€|eur\\b)?[${GS}]*[0-9]`, "dgu");
const TOT_AMOUNT = new RegExp(`\\btot[${GS}]*(?:€|eur\\b|[0-9][0-9.,]*[${GS}]*(?:%|euro\\b|procent\\b))`, "dgu");

const HEDGE_EQUIVALENTS: readonly Phrase[] = [
  { words: ["normaal", "gesproken"], cls: HEDGE_SOFTENER }, { words: ["normaliter"], cls: HEDGE_SOFTENER },
  { words: ["gewoonlijk"], cls: HEDGE_SOFTENER }, { words: ["doorgaans"], cls: HEDGE_SOFTENER },
  { words: ["meestal"], cls: HEDGE_SOFTENER }, { words: ["in", "het", "algemeen"], cls: HEDGE_SOFTENER },
  { words: ["over", "het", "algemeen"], cls: HEDGE_SOFTENER }, { words: ["als", "regel"], cls: HEDGE_SOFTENER },
  { words: ["in", "de", "meeste", "gevallen"], cls: HEDGE_SOFTENER }, { words: ["in", "beginsel"], cls: HEDGE_SOFTENER },
  { words: ["normally"], cls: HEDGE_SOFTENER }, { words: ["usually"], cls: HEDGE_SOFTENER },
  { words: ["generally"], cls: HEDGE_SOFTENER }, { words: ["in", "general"], cls: HEDGE_SOFTENER },
  { words: ["typically"], cls: HEDGE_SOFTENER }, { words: ["ordinarily"], cls: HEDGE_SOFTENER },
  { words: ["in", "most", "cases"], cls: HEDGE_SOFTENER }, { words: ["as", "a", "general", "rule"], cls: HEDGE_SOFTENER },
  { words: ["toegestaan"], cls: HEDGE_PERMISSION }, { words: ["mogelijk"], cls: HEDGE_PERMISSION },
  { words: ["mogelijkheid"], cls: HEDGE_PERMISSION }, { words: ["allowed"], cls: HEDGE_PERMISSION },
  { words: ["permitted"], cls: HEDGE_PERMISSION }, { words: ["possible"], cls: HEDGE_PERMISSION },
  { words: ["option"], cls: HEDGE_PERMISSION }, { words: ["optional"], cls: HEDGE_PERMISSION },
];

/** The classes hedgeEquivalents give the claim; a negated one gives none. */
function claimHedgeEquivalents(tokens: readonly string[]): Set<string> {
  const out = new Set<string>();
  for (const h of HEDGE_EQUIVALENTS) {
    for (const sp of findSpans(tokens, h.words)) {
      if (sp.start >= 1 && (tokens[sp.start - 1] === "zoveel" || tokens[sp.start - 1] === "zo")) continue;
      if (sp.start >= 2 && (tokens[sp.start - 2] === "zo" || tokens[sp.start - 2] === "as")) continue;
      if (h.cls === HEDGE_PERMISSION && !predicative(tokens, sp)) continue;
      let negated = false;
      for (let k = sp.start - 3; k < tokens.length && k <= sp.end + 2; k++) {
        if (k < 0 || (k >= sp.start && k < sp.end)) continue;
        if (POLARITY_MARKERS.has(tokens[k] as string)) negated = true;
      }
      if (!negated) out.add(h.cls);
    }
  }
  return out;
}

const PERMISSION_COPULAS: ReadonlySet<string> = new Set([
  "is", "are", "be", "was", "were", "been", "zijn", "wordt", "worden",
  "has", "have", "had", "heeft", "hebben", "biedt", "bieden",
]);

const PERMISSION_COMPLEMENTS: ReadonlySet<string> = new Set(["to", "that", "for", "om", "dat", "te"]);

function predicative(tokens: readonly string[], sp: Span): boolean {
  for (let k = sp.start - 3; k < sp.start; k++) {
    if (k >= 0 && PERMISSION_COPULAS.has(tokens[k] as string)) return true;
  }
  return sp.end < tokens.length && PERMISSION_COMPLEMENTS.has(tokens[sp.end] as string);
}

/** The first phrase found in tokens, joined; "" when none. */
export function hasAny(tokens: readonly string[], phrases: readonly (readonly string[])[]): string {
  for (const p of phrases) if (findSpans(tokens, p).length > 0) return p.join(" ");
  return "";
}

/** hedgeGuard: see the file comment. */
export function hedgeGuard(claim: string, claimLanguage: string, eu: EvidenceUnit, cfg: GuardConfig): string {
  if (cfg.fragment) return ""; // a lead-in fragment states no fact of its own
  const claimTokens = tokenizeV2(claim);
  const unitTokens = tokenizeV2(eu.text);
  const a = hasAny(claimTokens, ABSOLUTIZERS);
  if (a !== "" && hasAny(unitTokens, ABSOLUTIZERS) === "") {
    return `hedge guard: the claim says ${goQuote(a)}; the source states no such absolute`;
  }
  const cross =
    claimLanguage !== "" && eu.language !== "" && primaryLanguage(claimLanguage) !== primaryLanguage(eu.language);
  const c = new Carrier(new Set(claimTokens), cross, glossIdx(cfg.gloss));
  const claimNumbers = new Set(numbersIn(claim, claimLanguage, verbatimIn(eu.text, eu.language)).map((m) => m.reading.key));
  let best = "";
  let bestN = 0;
  let tie = false;
  for (const s of goSplit(sentenceBreak, softJoin(eu.text))) {
    let n = 0;
    const seen = new Set<string>();
    for (const t of tokenizeV2(s)) {
      const [has] = c.carried(t);
      if (!seen.has(t) && has && conditionContent(t)) {
        seen.add(t);
        n++;
      }
    }
    for (const m of numbersIn(s, eu.language)) if (claimNumbers.has(m.reading.key)) n += 2;
    if (n > bestN) {
      best = s;
      bestN = n;
      tie = false;
    } else if (n === bestN && n > 0) {
      tie = true;
    }
  }
  if (bestN < 2 || tie) return "";
  const unitHedges = hedgesIn(tokenizeV2(best), best);
  const claimHedges = hedgesIn(claimTokens, claim);
  for (const cls of claimHedgeEquivalents(claimTokens)) claimHedges.set(cls, cls);
  for (const cls of [HEDGE_PERMISSION, HEDGE_UPPER, HEDGE_SOFTENER]) {
    const word = unitHedges.get(cls);
    if (word === undefined) continue;
    if (claimHedges.has(cls)) continue;
    if (cls === HEDGE_UPPER && matches(CLAIM_RANGE, goLower(claim))) continue;
    if (cls === HEDGE_UPPER && word === "tot" && matches(TO_SAME_AMOUNT, goLower(claim))) continue;
    return `hedge guard: the source limits it (${cls} ${goQuote(word)}) and the claim states it without`;
  }
  return "";
}
