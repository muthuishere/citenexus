// The condition guard: a model-admitted claim that drops the unit's condition —
// port of golang/answer/verify_conditions.go.
//
// It finds the unit sentence the claim follows (the most shared content words,
// at least two) and reads its restrictors: an opener and what follows it, a
// verb-first conditional sentence, a scope qualifier before a shared word, and
// a coordinated requirement dropped from inside the claim's span. A restrictor
// whose content words the claim lacks refuses the claim. Across languages only
// through the caller's glossary; a glossary miss never refuses and never
// admits. Can only refuse.

import { isStopword } from "../gate/gate.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { containsAny, goLower, goQuote, goSplit, pad2, runeLen } from "./gotext.js";
import { dateSpans, datesIn } from "./numbers.js";
import { primaryLanguage } from "./verify-answer.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { BOUND_LOWER, boundDirections, clauseBreak } from "./verify-guards.js";
import type { GuardConfig } from "./verify-guards.js";
import { CONTEXT_STOP, softJoin } from "./verify-guards-model.js";
import { hasAny, hedgesIn } from "./verify-hedges.js";
import { sentenceBreak } from "./verify-parties.js";
import { isArticle } from "./verify-roles.js";
import type { ActorLexicon } from "./verify-roles.js";
import { crossConditionMarkers, droppedConjunct } from "./verify-conjunct-presence.js";
import { GROUP_VERBS, boundOrNegation } from "./verify-exclusions.js";
import { glossEmpty, glossIdx } from "./glossary.js";

const CONDITION_OPENERS: ReadonlySet<string> = new Set([
  "mits", "indien", "tenzij", "voorwaarde", "alleen", "uitsluitend",
  "enkel", "slechts", "eerst", "pas", "zolang", "behalve", "uitgezonderd",
  "provided", "unless", "only", "solely", "first", "except", "once",
]);

const CONDITION_PHRASES: readonly (readonly [string, string])[] = [
  ["ten", "minste"], ["met", "toestemming"], ["at", "least"], ["with", "permission"],
];

const SUBORDINATING_OPENERS: ReadonlySet<string> = new Set([
  "mits", "indien", "tenzij", "zolang", "voorwaarde", "provided", "unless", "once",
]);

const CONCESSIVES: readonly (readonly string[])[] = [
  ["even", "if"], ["even", "when"], ["even", "though"], ["regardless", "of", "whether"],
  ["zelfs", "als"], ["zelfs", "wanneer"], ["zelfs", "indien"], ["ook", "als"], ["ook", "wanneer"],
  ["ongeacht", "of"],
];

const EXCEPTION_OPENERS: readonly (readonly string[])[] = [
  ["tenzij"], ["mits"], ["indien"], ["behalve"], ["uitgezonderd"], ["alleen", "als"], ["alleen", "wanneer"],
  ["unless"], ["provided"], ["except"], ["only", "if"], ["only", "when"],
];

const CLAIM_CONDITION_MARKERS: ReadonlySet<string> = new Set([
  "als", "wanneer", "zodra", "indien", "die", "wie", "if", "when", "who", "whoever",
]);

const PARTY_RESTRICTORS: ReadonlySet<string> = new Set(["met", "die", "with", "who"]);

export const SCOPE_QUALIFIERS: ReadonlySet<string> = new Set([
  "onbetaald", "onbetaalde", "betaald", "betaalde", "aanvullend", "aanvullende",
  "bijzonder", "bijzondere", "vast", "vaste", "tijdelijk", "tijdelijke",
  "variabel", "variabele", "gewoon", "gewone",
  "unpaid", "paid", "additional", "special", "fixed", "variable",
  "regular", "temporary", "permanent",
]);

const CONDITIONAL_VERB_SUBJECTS: ReadonlySet<string> = new Set(["je", "jij", "u", "de", "het"]);

export function conditionContent(t: string): boolean {
  if (isStopword(t)) return false;
  if (CONTEXT_STOP.has(t)) return false;
  return runeLen(t) >= 4 || containsAny(t, "0123456789");
}

/** Whether the claim carries unit word w: directly, or (other language) through
 * a glossary translation. */
export class Carrier {
  /** VerifyOptions.conjunctPresence only: the glossary may show a word carried, never missing. */
  satisfyOnly = false;
  constructor(
    readonly claim: Set<string>,
    readonly crossLang: boolean,
    readonly translations: ReadonlyMap<string, string[][]> | null,
  ) {}

  /** [has, known]; known is false when w has no glossary entry across languages. */
  carried(w: string): [boolean, boolean] {
    if (this.claim.has(w)) return [true, true];
    const r = runeLen(w);
    if (r >= 6) {
      for (const t of this.claim) {
        const tr = runeLen(t);
        if (tr >= 6 && (t.startsWith(w) || w.startsWith(t)) && Math.abs(tr - r) <= 3) return [true, true];
      }
    }
    if (!this.crossLang) return [false, true];
    const trs = this.translations?.get(w);
    if (trs === undefined) {
      if (containsAny(w, "0123456789")) return [false, true]; // a number reads the same
      return [false, false];
    }
    for (const tr of trs) if (tr.every((t) => this.claim.has(t))) return [true, true];
    if (this.satisfyOnly) return [false, false];
    return [false, true];
  }

  clone(): Carrier {
    const c = new Carrier(this.claim, this.crossLang, this.translations);
    c.satisfyOnly = this.satisfyOnly;
    return c;
  }
}

/** Single-token term -> its translations (golang glossaryIndex). */
export function glossaryIndex(glossary: readonly (readonly [string, string])[]): Map<string, string[][]> {
  const out = new Map<string, string[][]>();
  for (const pair of glossary) {
    for (let k = 0; k < 2; k++) {
      const from = tokenizeV2(pair[k] as string);
      const to = tokenizeV2(pair[1 - k] as string);
      if (from.length === 1 && to.length > 0) {
        const key = from[0] as string;
        const list = out.get(key);
        if (list === undefined) out.set(key, [to]);
        else list.push(to);
      }
    }
  }
  return out;
}

/** conditionGuard: see the file comment. */
export function conditionGuard(claim: string, claimLanguage: string, eu: EvidenceUnit, cfg: GuardConfig): string {
  const cross =
    claimLanguage !== "" && eu.language !== "" && primaryLanguage(claimLanguage) !== primaryLanguage(eu.language);
  if (cross && glossEmpty(cfg.gloss)) return "";
  claim = canonicalDates(claim, claimLanguage);
  const euText = canonicalDates(eu.text, eu.language);
  const claimTokens = tokenizeV2(claim);
  const c = new Carrier(new Set(claimTokens), cross, glossIdx(cfg.gloss));
  c.satisfyOnly = cfg.conjunctPresence && cross && hasAny(claimTokens, crossConditionMarkers) !== "";
  const claimBounds = boundDirections(claimTokens);
  const shared = (t: string): boolean => conditionContent(t) && c.carried(t)[0];
  let ties: string[] = [];
  const previous = new Map<string, string>();
  let bestN = 0;
  const claimHedges = hedgesIn(claimTokens, claim);
  let prev = "";
  for (const s of goSplit(sentenceBreak, softJoin(euText))) {
    previous.set(s, prev);
    prev = s;
    let n = 0;
    const seen = new Set<string>();
    for (const t of tokenizeV2(s)) {
      let [has] = c.carried(t);
      if (!has && cross) {
        if (actorTerm(t, cfg.actors) && claimNamesRole(c.claim, t, cfg.actors)) has = true;
        for (const cls of hedgesIn([t], t).keys()) if (claimHedges.has(cls)) has = true;
      }
      if (!seen.has(t) && has && !isStopword(t) && !isContextStop(t)) {
        seen.add(t);
        n++;
      }
    }
    if (n > bestN) {
      ties = [s];
      bestN = n;
    } else if (n === bestN && n > 0) {
      ties.push(s);
    }
  }
  if (bestN < 2) return "";

  const lacks = (words: readonly string[], half: boolean): [boolean, string] => {
    let content = 0;
    let known = 0;
    let missing = 0;
    let first = "";
    for (const w of words) {
      if (!conditionContent(w)) continue;
      content++;
      const [has, ok] = c.carried(w);
      if (!ok) continue;
      known++;
      if (!has) {
        missing++;
        if (first === "") first = w;
      }
    }
    if (content === 0 || known === 0) return [false, ""];
    if (c.crossLang) return [missing === known && 2 * known >= content, first];
    if (half) return [2 * missing >= content && missing > 0, first];
    return [missing === content, first];
  };
  let claimConditioned = false;
  for (let i = 0; i < claimTokens.length; i++) {
    const t = claimTokens[i] as string;
    if (CLAIM_CONDITION_MARKERS.has(t)) claimConditioned = true;
    if (t === "as" && i + 2 < claimTokens.length && claimTokens[i + 1] === "long" && claimTokens[i + 2] === "as") {
      claimConditioned = true;
    }
    if (CONDITION_OPENERS.has(t) && !(i > 0 && (claimTokens[i - 1] === "niet" || claimTokens[i - 1] === "not"))) {
      claimConditioned = true;
    }
  }
  const lacksSegment = (words: readonly string[]): [boolean, string] => {
    const [ok, w] = lacks(words, true);
    if (!ok || c.crossLang || !claimConditioned) return [ok, w];
    let content = 0;
    let missing = 0;
    for (const x of words) {
      if (!conditionContent(x)) continue;
      content++;
      if (!c.carried(x)[0]) missing++;
    }
    return [2 * missing > content, w];
  };
  const refuse = (kind: string, word: string): string =>
    `condition guard: the passage restricts it (${kind} ${goQuote(word)}) and the claim drops it`;

  if (c.satisfyOnly) {
    const strict = c.clone();
    strict.satisfyOnly = false;
    for (const bestText of ties) {
      const [w, n] = droppedConjunct(claim, bestText, eu.language, strict);
      if (w !== "") {
        return `condition guard: the passage attaches ${n} conditions and the claim carries only part of them (${goQuote(w)} missing)`;
      }
    }
  }
  const claimConcedes = hasAny(claimTokens, CONCESSIVES) !== "";
  for (const bestText of ties) {
    const best = tokenizeV2(bestText);
    if (claimConcedes && hasAny(best, CONCESSIVES) === "") {
      const w = hasAny(best, EXCEPTION_OPENERS);
      if (w !== "") {
        return `condition guard: the passage makes it conditional (${goQuote(w)}) and the claim holds it regardless (${goQuote(hasAny(claimTokens, CONCESSIVES))})`;
      }
    }
    if (
      best.length > 1 &&
      (best[0] === "dan" ||
        best[0] === "then" ||
        (best.length > 2 && best[0] === "in" && best[1] === "dat" && best[2] === "geval") ||
        (best.length > 2 && best[0] === "in" && best[1] === "that" && best[2] === "case"))
    ) {
      const cond = previous.get(bestText) ?? "";
      if (cond !== "") {
        const [ok, w] = lacks(tokenizeV2(cond), true);
        if (ok) return refuse("condition", w);
      }
    }
    if (best.length > 2) {
      if (
        CONDITIONAL_VERB_SUBJECTS.has(best[1] as string) &&
        !isStopword(best[0] as string) &&
        !isContextStop(best[0] as string)
      ) {
        for (let i = 0; i < best.length; i++) {
          if (best[i] === "dan" && i > 2 && bestText.includes(", dan")) {
            const [ok, w] = lacks(best.slice(0, i), false);
            if (ok) return refuse("condition", w);
            break;
          }
        }
      }
    }
    for (const clause of goSplit(clauseBreak, softJoin(bestText))) {
      const toks = tokenizeV2(clause);
      const outOfScope: boolean[] = new Array<boolean>(toks.length).fill(false);
      for (let i = 1; i < toks.length; i++) {
        const subject = i - 1 === 0 || (i - 1 === 1 && isArticle(toks[0] as string));
        if (
          PARTY_RESTRICTORS.has(toks[i] as string) &&
          subject &&
          actorTerm(toks[i - 1] as string, cfg.actors) &&
          !claimNamesActor(c.claim, toks[i - 1] as string, cfg.actors)
        ) {
          for (let k = i; k < toks.length; k++) outOfScope[k] = true;
          break;
        }
      }
      for (let i = 0; i < toks.length; i++) {
        if (outOfScope[i]) continue;
        const ti = toks[i] as string;
        let start = -1;
        const negated = i > 0 && (toks[i - 1] === "niet" || toks[i - 1] === "not");
        if (CONDITION_OPENERS.has(ti) && !negated) {
          start = i + 1;
          if (EXCLUSION_OPENERS.has(ti) && boundOrNegation(claimTokens)) start = -1;
        }
        for (const ph of CONDITION_PHRASES) {
          if (i + 1 < toks.length && ti === ph[0] && toks[i + 1] === ph[1]) {
            start = i + 1;
            if (claimBounds.has(BOUND_LOWER) && (ph[1] === "minste" || ph[1] === "least")) start = -1;
          }
        }
        if (
          PARTY_RESTRICTORS.has(ti) &&
          i > 0 &&
          (actorTerm(toks[i - 1] as string, cfg.actors) || inSubjectOfRole(toks, i, cfg.actors))
        ) {
          start = i + 1;
        }
        if (start < 0 || start >= toks.length) continue;
        let end = start;
        while (end < toks.length && !shared(toks[end] as string)) end++;
        if (SUBORDINATING_OPENERS.has(ti)) {
          let inClause = 0;
          let inSentence = 0;
          for (const t of toks.slice(start)) if (shared(t)) inClause++;
          for (const t of best) if (shared(t)) inSentence++;
          if (inSentence > inClause) end = toks.length;
        }
        if (!CONDITION_OPENERS.has(ti) && end === start) continue;
        const [ok, w] = lacksSegment(toks.slice(start, end));
        if (ok) return refuse("condition", ti + " … " + w);
      }
      for (let i = 0; i + 1 < toks.length; i++) {
        if (!SCOPE_QUALIFIERS.has(toks[i] as string)) continue;
        let j = i + 1;
        while (j + 1 < toks.length && (toks[j] === "en" || toks[j] === "and")) j += 2;
        if (j < toks.length && shared(toks[j] as string)) {
          const [ok, w] = lacks([toks[i] as string], false);
          if (ok) return refuse("qualifier", w);
        }
      }
      for (let i = 0; i + 3 < toks.length; i++) {
        if (
          shared(toks[i] as string) &&
          (toks[i + 1] === "en" || toks[i + 1] === "and") &&
          conditionContent(toks[i + 2] as string) &&
          shared(toks[i + 3] as string)
        ) {
          const [ok, w] = lacks([toks[i + 2] as string], false);
          if (ok) return refuse("requirement", w);
        }
      }
    }
  }
  return "";
}

export function actorTerm(t: string, lexicon: ActorLexicon): boolean {
  for (const terms of Object.values(lexicon.actors)) if (terms.includes(t)) return true;
  return false;
}

/** The claim names the same actor as unit term t (any term of its class). */
export function claimNamesActor(claim: ReadonlySet<string>, t: string, lexicon: ActorLexicon): boolean {
  for (const [id, terms] of Object.entries(lexicon.actors)) {
    if (id === lexicon.secondPerson) {
      for (const x of lexicon.secondPersonTerms) if (claim.has(x) && terms.includes(t)) return true;
    }
    if (!terms.includes(t)) continue;
    for (const x of terms) if (claim.has(x)) return true;
  }
  return false;
}

export function hasTerm(terms: readonly string[], t: string): boolean {
  return terms.includes(t);
}

export function isContextStop(t: string): boolean {
  return CONTEXT_STOP.has(t);
}

/** Each date replaced with one token, "d0106" (+ " y2026"). */
export function canonicalDates(text: string, language: string): string {
  const [dates] = datesIn(text, language);
  if (dates.length === 0) return text;
  const lowered = goLower(text);
  let b = "";
  let last = 0;
  for (const sp of dateSpans(lowered, language)) {
    b += lowered.slice(last, sp.start);
    const d = sp.key;
    if (d.ambiguous !== "") {
      b += " " + d.ambiguous + " ";
    } else {
      b += ` d${pad2(d.day)}${pad2(d.month)} `;
      if (d.year !== 0) b += `y${d.year} `;
    }
    last = sp.end;
  }
  return b + lowered.slice(last);
}

const EXCLUSION_OPENERS: ReadonlySet<string> = new Set(["behalve", "uitgezonderd", "except"]);

/** The claim names t's actor class by an explicit role term, not a pronoun. */
export function claimNamesRole(claim: ReadonlySet<string>, t: string, lexicon: ActorLexicon): boolean {
  for (const terms of Object.values(lexicon.actors)) {
    if (!terms.includes(t)) continue;
    for (const x of terms) if (claim.has(x)) return true;
  }
  return false;
}

/** Position i lies inside the subject of a clause that opens with a role. */
function inSubjectOfRole(toks: readonly string[], i: number, lexicon: ActorLexicon): boolean {
  let start = 0;
  if (toks.length > 1 && isArticle(toks[0] as string)) start = 1;
  if (start >= toks.length || !actorTerm(toks[start] as string, lexicon)) return false;
  for (let k = start + 1; k < i; k++) if (GROUP_VERBS.has(toks[k] as string)) return false;
  return true;
}
