// The exclusion guard: a claim that asserts a fact for a group the unit
// EXCLUDES from it — port of golang/answer/verify_exclusions.go.
//
// A unit sentence excludes a group with a marker (behalve, except, not for, …),
// by a negated "voor G"/"for G" sentence, or by G as subject of an excluded
// predicate. The claim is refused when it names an excluded group or speaks
// about everyone, unless it restates the exclusion itself. A group word no
// reader can read gives no verdict. Can only refuse.

import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { containsAny, goQuote, goSplit } from "./gotext.js";
import { primaryLanguage } from "./verify-answer.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { Carrier, actorTerm, conditionContent, hasTerm } from "./verify-conditions.js";
import { equalTokens } from "./verify-guards.js";
import type { GuardConfig } from "./verify-guards.js";
import { numberValue, softJoin, unitOf } from "./verify-guards-model.js";
import { sentenceBreak } from "./verify-parties.js";
import { glossIdx } from "./glossary.js";

const EXCLUSION_MARKERS: readonly (readonly string[])[] = [
  ["behalve"], ["uitgezonderd"], ["met", "uitzondering", "van"], ["niet", "voor"],
  ["niet", "van", "toepassing", "op"], ["except"], ["excluding"], ["other", "than"],
  ["with", "the", "exception", "of"], ["not", "applicable", "to"], ["not", "for"],
];

const EXCLUDED_PREDICATES: readonly (readonly string[])[] = [
  ["zijn", "uitgesloten"], ["is", "uitgesloten"], ["hebben", "geen", "recht"], ["heeft", "geen", "recht"],
  ["komen", "niet", "in", "aanmerking"], ["komt", "niet", "in", "aanmerking"],
  ["are", "excluded"], ["is", "excluded"], ["are", "not", "entitled"], ["is", "not", "entitled"],
  ["are", "not", "eligible"], ["is", "not", "eligible"], ["are", "not", "enrolled"], ["is", "not", "enrolled"],
];

const UNIVERSAL_WORDS: ReadonlySet<string> = new Set([
  "alle", "iedereen", "iedere", "elke", "ieder", "all", "every", "everyone", "everybody",
]);

export const GROUP_VERBS: ReadonlySet<string> = new Set([
  "geldt", "gelden", "is", "zijn", "heeft", "hebben", "komt", "komen",
  "krijgt", "krijgen", "ontvangt", "ontvangen", "kan", "kunnen", "mag", "mogen",
  "applies", "apply", "are", "has", "have", "can", "may", "receive", "receives",
]);

/** Separates a group's head from its prepositional qualifier. */
const QUALIFIER_MARK = "|";

export const GROUP_PREPOSITIONS: ReadonlySet<string> = new Set([
  "in", "met", "van", "vanaf", "op", "bij", "with", "from", "of", "on", "at",
]);

/** A segment's groups, split at en/and/or/of, each as its content words. */
function splitGroups(tokens: readonly string[]): string[][] {
  const out: string[][] = [];
  let cur: string[] = [];
  const flush = (): void => {
    if (cur.length > 0) out.push(cur);
    cur = [];
  };
  for (const t of tokens) {
    switch (t) {
      case "en":
      case "and":
      case "or":
      case "of":
        flush();
        continue;
      case "die":
      case "dat":
      case "who":
      case "that":
      case "which":
      case "waarvan":
        flush();
        return out;
    }
    if (GROUP_PREPOSITIONS.has(t) && cur.length > 0 && !hasTerm(cur, QUALIFIER_MARK)) {
      cur.push(QUALIFIER_MARK);
      continue;
    }
    if (conditionContent(t)) cur.push(t);
  }
  flush();
  return out;
}

/** The groups a unit sentence excludes. */
function excludedGroups(tokens: readonly string[]): string[][] {
  const groups: string[][] = [];
  for (let i = 0; i < tokens.length; i++) {
    for (const m of EXCLUSION_MARKERS) {
      if (i + m.length > tokens.length || !equalTokens(tokens.slice(i, i + m.length), m)) continue;
      const j = i + m.length;
      let k = j;
      while (k < tokens.length && !GROUP_VERBS.has(tokens[k] as string)) k++;
      groups.push(...splitGroups(tokens.slice(j, k)));
    }
  }
  let markers = 0;
  for (const t of tokens) if (t === "niet" || t === "not" || t === "geen" || t === "no") markers++;
  if (tokens.length > 1 && (tokens[0] === "voor" || tokens[0] === "for") && markers > 0) {
    let k = 1;
    while (k < tokens.length && !GROUP_VERBS.has(tokens[k] as string)) k++;
    groups.push(...splitGroups(tokens.slice(1, k)));
  }
  for (let i = 0; i < tokens.length; i++) {
    for (const p of EXCLUDED_PREDICATES) {
      if (i + p.length <= tokens.length && equalTokens(tokens.slice(i, i + p.length), p)) {
        groups.push(...splitGroups(tokens.slice(0, i)));
      }
    }
  }
  return groups;
}

/** exclusionGuard: see the file comment. */
export function exclusionGuard(claim: string, claimLanguage: string, eu: EvidenceUnit, cfg: GuardConfig): string {
  const cross =
    claimLanguage !== "" && eu.language !== "" && primaryLanguage(claimLanguage) !== primaryLanguage(eu.language);
  const claimTokens = tokenizeV2(claim);
  const c = new Carrier(new Set(claimTokens), cross, glossIdx(cfg.gloss));
  if (excludedGroups(claimTokens).length > 0 || boundOrNegation(claimTokens)) return "";
  let universal = false;
  for (let i = 0; i < claimTokens.length; i++) {
    if (!UNIVERSAL_WORDS.has(claimTokens[i] as string)) continue;
    if (i + 1 < claimTokens.length) {
      const next = claimTokens[i + 1] as string;
      if (numberValue(next, claimLanguage)[1]) continue;
      if (unitOf(next)[2]) continue;
    }
    universal = true;
  }
  const carried = (w: string): [boolean, boolean] => {
    for (const terms of Object.values(cfg.actors.actors)) {
      if (hasTerm(terms, w)) {
        for (const x of terms) if (c.claim.has(x)) return [true, true];
        return [false, true];
      }
    }
    return c.carried(w);
  };
  for (const s of goSplit(sentenceBreak, softJoin(eu.text))) {
    for (const g of excludedGroups(tokenizeV2(s))) {
      if (universal) {
        return `exclusion guard: the claim speaks about everyone; the passage excludes ${goQuote(withoutMark(g).join(" "))}`;
      }
      let all = true;
      let known = 0;
      let qualifier = false;
      let qualifierKnown = 0;
      let qualifierWords = 0;
      let qualifierNumber = false;
      let headRole = false;
      for (const w of g) {
        if (w === QUALIFIER_MARK) break;
        if (actorTerm(w, cfg.actors)) headRole = true;
      }
      for (const w of g) {
        if (w !== QUALIFIER_MARK && !qualifier && headRole && !actorTerm(w, cfg.actors)) continue;
        if (w === QUALIFIER_MARK) {
          qualifier = true;
          continue;
        }
        if (qualifier) {
          qualifierWords++;
          if (containsAny(w, "0123456789")) qualifierNumber = true;
        }
        const [has, ok] = carried(w);
        if (!ok) continue;
        known++;
        if (qualifier) qualifierKnown++;
        if (!has) all = false;
      }
      if (qualifier && (qualifierKnown === 0 || (qualifierKnown < qualifierWords && !qualifierNumber))) continue;
      if (known > 0 && all) return `exclusion guard: the passage excludes ${goQuote(withoutMark(g).join(" "))}`;
    }
  }
  return "";
}

export function boundOrNegation(tokens: readonly string[]): boolean {
  for (const t of tokens) {
    switch (t) {
      case "niet":
      case "not":
      case "geen":
      case "no":
      case "never":
      case "nooit":
      case "without":
      case "zonder":
      case "behalve":
      case "except":
      case "excluding":
        return true;
    }
  }
  return false;
}

function withoutMark(g: readonly string[]): string[] {
  return g.filter((w) => w !== QUALIFIER_MARK);
}
