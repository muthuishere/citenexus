// Party swaps and value rows — port of golang/answer/verify_parties.go.
//
// PARTY SWAP: a claim that does not align with any sentence of the unit as
// written, but does once one of its parties is replaced by another party of the
// unit (or two are exchanged). A pair binds its values (bindValue).
// VALUE ROW: a number stated for one period moved to another.
// SUBJECT SWAP: across languages, through the glossary, a claim's
// "party + verb" bound to the unit sentences with that verb.
// All can only refuse.

import { isStopword } from "../gate/gate.js";
import { align } from "../gate/verify-v2.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { GS, byteLen, cmpGo, containsAny, goQuote, goSplit, goTrim, runeLen, runes, trimPrefix } from "./gotext.js";
import { type VerbatimNumbers, clockTimes, numbersIn, verbatimIn } from "./numbers.js";
import { primaryLanguage } from "./verify-answer.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { actorTerm, hasTerm } from "./verify-conditions.js";
import { equalTokens } from "./verify-guards.js";
import type { GuardConfig } from "./verify-guards.js";
import { CONTEXT_STOP, qsplit, quantities, sameQuantityIn, softJoin } from "./verify-guards-model.js";
import { lowerWords, numberWordKeys, sharesKey } from "./verify-qualifier-pairs.js";
import { ROLE_TRIM, roleClauses } from "./verify-roles.js";
import type { ActorLexicon } from "./verify-roles.js";
import { SEPARABLE_PARTICLES, glossClass, glossEmpty, glossIdx, glossSep, glossSeps } from "./glossary.js";

const PARTY_DETERMINERS: ReadonlySet<string> = new Set([
  "de", "het", "een", "the", "a", "an", "zijn", "haar", "hun", "his", "her", "their",
]);

const ARTICLES: ReadonlySet<string> = new Set(["de", "het", "een", "the", "a", "an"]);

/** golang sentenceBreak: `[.!?;]+(\s|$)|\n`. */
export const sentenceBreak = new RegExp(`[.!?;]+([${GS}]|$)|\\n`, "dgu");

function withoutArticles(tokens: readonly string[]): string[] {
  return tokens.filter((t) => !ARTICLES.has(t));
}

export function partyWord(t: string): boolean {
  if (runeLen(t) < 3 || containsAny(t, "0123456789") || isStopword(t)) return false;
  return !CONTEXT_STOP.has(t);
}

/** The determiner-introduced noun phrases of the unit: one word, or "X van Y". */
function unitParties(sentences: readonly (readonly string[])[]): string[][] {
  const seen = new Set<string>();
  const out: string[][] = [];
  for (const toks of sentences) {
    for (let i = 0; i + 1 < toks.length; i++) {
      if (!PARTY_DETERMINERS.has(toks[i] as string) || !partyWord(toks[i + 1] as string)) continue;
      const phrases: string[][] = [[toks[i + 1] as string]];
      if (i + 3 < toks.length && toks[i + 2] === "van" && partyWord(toks[i + 3] as string)) {
        phrases.push([toks[i + 1] as string, "van", toks[i + 3] as string]);
      }
      for (const p of phrases) {
        const k = p.join(" ");
        if (!seen.has(k)) {
          seen.add(k);
          out.push(p);
        }
      }
    }
  }
  return out;
}

/** [start, end) */
export interface Span {
  start: number;
  end: number;
}

export function findSpans(tokens: readonly string[], phrase: readonly string[]): Span[] {
  const out: Span[] = [];
  for (let i = 0; i + phrase.length <= tokens.length; i++) {
    if (equalTokens(tokens.slice(i, i + phrase.length), phrase)) out.push({ start: i, end: i + phrase.length });
  }
  return out;
}

function replaceSpans(tokens: readonly string[], repl: readonly (readonly [Span, readonly string[]])[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < tokens.length; ) {
    let done = false;
    for (const [s, r] of repl) {
      if (s.start === i) {
        out.push(...r);
        i = s.end;
        done = true;
        break;
      }
    }
    if (!done) {
      out.push(tokens[i] as string);
      i++;
    }
  }
  return out;
}

/** partySwapGuard: see the file comment. */
export function partySwapGuard(claim: string, claimLanguage: string, eu: EvidenceUnit, lexicon: ActorLexicon): string {
  const sentences: string[][] = [];
  const bare: string[][] = [];
  for (const s of goSplit(sentenceBreak, softJoin(eu.text))) {
    const toks = tokenizeV2(s);
    if (toks.length > 0) {
      sentences.push(toks);
      bare.push(withoutArticles(toks));
    }
  }
  const claimTokens = withoutArticles(tokenizeV2(claim));
  if (claimTokens.length === 0) return "";
  const aligns = (tokens: readonly string[]): boolean => bare.some((s) => align(tokens, s) !== null);
  const parties = unitParties(sentences);
  const binding = (o: readonly string[], p: readonly string[]): number =>
    bindValue(claim, claimLanguage, eu.text, eu.language, o, p);
  if (aligns(claimTokens)) return pairValueGuard(claim, claimLanguage, eu);
  const classOf = (p: readonly string[]): string => {
    if (p.length !== 1) return "";
    for (const [id, terms] of Object.entries(lexicon.actors)) if (terms.includes(p[0] as string)) return id;
    return "";
  };
  interface Occurrence {
    at: Span;
    party: readonly string[];
    pronoun: boolean;
  }
  const inClaim: Occurrence[] = [];
  for (const p of parties) for (const s of findSpans(claimTokens, p)) inClaim.push({ at: s, party: p, pronoun: false });
  for (const t of lexicon.secondPersonTerms) {
    for (const s of findSpans(claimTokens, [t])) inClaim.push({ at: s, party: [t], pronoun: true });
  }
  const same = (a: readonly string[], b: readonly string[], aPronoun: boolean): boolean => {
    if (equalTokens(a, b)) return true;
    let ca = classOf(a);
    const cb = classOf(b);
    if (aPronoun) ca = lexicon.secondPerson;
    return ca !== "" && ca === cb;
  };
  for (const o of inClaim) {
    for (const p of parties) {
      if (same(o.party, p, o.pronoun) || (o.pronoun && classOf(p) !== "")) continue;
      if (aligns(replaceSpans(claimTokens, [[o.at, p]]))) {
        const b = binding(o.party, p);
        if (b === BIND_OWN || b === BIND_UNRESOLVED) continue;
        return `role guard: ${goQuote(o.party.join(" "))} where the passage says ${goQuote(p.join(" "))}`;
      }
    }
  }
  for (let i = 0; i < inClaim.length; i++) {
    const a = inClaim[i] as Occurrence;
    for (const b of inClaim.slice(i + 1)) {
      if (a.at.end > b.at.start && b.at.end > a.at.start) continue;
      if (same(a.party, b.party, a.pronoun)) continue;
      if (aligns(replaceSpans(claimTokens, [[a.at, b.party], [b.at, a.party]]))) {
        return `role guard: ${goQuote(a.party.join(" "))} and ${goQuote(b.party.join(" "))} are exchanged`;
      }
    }
  }
  return "";
}

/** A number stated with one word of a pair the unit binds to the other word. */
export function pairValueGuard(claim: string, claimLanguage: string, eu: EvidenceUnit): string {
  const sentences: string[][] = [];
  for (const s of goSplit(sentenceBreak, softJoin(eu.text))) {
    const toks = tokenizeV2(s);
    if (toks.length > 0) sentences.push(toks);
  }
  const claimTokens = withoutArticles(tokenizeV2(claim));
  const parties = unitParties(sentences);
  for (const o of parties) {
    if (findSpans(claimTokens, o).length === 0) continue;
    for (const p of parties) {
      if (equalTokens(o, p) || findSpans(claimTokens, p).length > 0 || !counterpartOf(o, p, sentences)) continue;
      if (bindValue(claim, claimLanguage, eu.text, eu.language, o, p) === BIND_OTHER) {
        return `role guard: ${goQuote(o.join(" "))} where the passage says ${goQuote(p.join(" "))}`;
      }
    }
  }
  return "";
}

const BIND_NO_NUMBER = -1;
const BIND_UNRESOLVED = 0;
const BIND_OWN = 1;
const BIND_OTHER = 2;

/** Which of own/other the unit binds the claim's numbers to. */
function bindValue(
  claim: string,
  claimLanguage: string,
  unit: string,
  unitLanguage: string,
  own: readonly string[],
  other: readonly string[],
): number {
  const claimKeys: string[][] = [];
  const verbatim = verbatimIn(unit, unitLanguage);
  for (const c of roleClauses(claim)) {
    for (const keys of numberWordKeys(c, claimLanguage, verbatim).values()) claimKeys.push(keys);
  }
  if (claimKeys.length === 0) return BIND_NO_NUMBER;
  let toOther = false;
  for (const c of roleClauses(unit)) {
    const words = lowerWords(c).map((w) => goTrim(w, ROLE_TRIM + ".,;:"));
    const positions = (phrase: readonly string[]): number[] => {
      const out: number[] = [];
      for (let i = 0; i < words.length; i++) {
        let k = 0;
        let j = i;
        while (j < words.length && k < phrase.length) {
          if (words[j] === phrase[k]) {
            k++;
            j++;
            continue;
          }
          if (ARTICLES.has(words[j] as string) && k > 0) {
            j++;
            continue;
          }
          break;
        }
        if (k === phrase.length) out.push(i);
      }
      return out;
    };
    const po = positions(own);
    const pp = positions(other);
    const governor = (at: number): number => {
      const before = (ps: readonly number[]): number => {
        let best = -1;
        for (const x of ps) if (x < at && x > best) best = x;
        return best;
      };
      const bo = before(po);
      const bp = before(pp);
      if (bo > bp) return BIND_OWN;
      if (bp > bo) return BIND_OTHER;
      if (bo >= 0) return BIND_UNRESOLVED;
      const after = (ps: readonly number[]): number => {
        let best = -1;
        for (const x of ps) if (x > at && (best < 0 || x < best)) best = x;
        return best;
      };
      const ao = after(po);
      const ap = after(pp);
      if (ao >= 0 && (ap < 0 || ao < ap)) return BIND_OWN;
      if (ap >= 0 && (ao < 0 || ap < ao)) return BIND_OTHER;
      return BIND_UNRESOLVED;
    };
    for (const [at, ukeys] of numberWordKeys(c, unitLanguage)) {
      for (const keys of claimKeys) {
        if (!sharesKey(keys, ukeys)) continue;
        const g = governor(at);
        if (g === BIND_OWN) return BIND_OWN;
        if (g === BIND_OTHER) toOther = true;
      }
    }
  }
  return toOther ? BIND_OTHER : BIND_UNRESOLVED;
}

/** Party p is the other word of a pair with o — a shared head. */
function counterpartOf(o: readonly string[], p: readonly string[], sentences: readonly (readonly string[])[]): boolean {
  if (o.length !== 1 || p.length !== 1) return false;
  const a = runes(o[0] as string);
  const b = runes(p[0] as string);
  let common = 0;
  while (common < a.length && common < b.length && a[a.length - 1 - common] === b[b.length - 1 - common]) common++;
  if (common >= 4 && a.length > common && b.length > common) return true;
  const next = (w: string): Set<string> => {
    const out = new Set<string>();
    for (const s of sentences) {
      for (let i = 0; i + 1 < s.length; i++) if (s[i] === w && partyWord(s[i + 1] as string)) out.add(s[i + 1] as string);
    }
    return out;
  };
  const no = next(o[0] as string);
  const np = next(p[0] as string);
  for (const w of no) if (np.has(w)) return true;
  return false;
}

/** valueRowGuard: see the file comment. */
export function valueRowGuard(claim: string, claimLanguage: string, eu: EvidenceUnit): string {
  const verbatim = verbatimIn(eu.text, eu.language); // the claim's copied numbers keep the unit's reading
  const periods = (clause: string, language: string, own: string, vb?: VerbatimNumbers): Set<string> => {
    const out = new Set<string>();
    for (const q of quantities(clause, language, vb)) if (qsplit(q)[0] !== own) out.add(q);
    return out;
  };
  const [, unitText] = clockTimes(eu.text);
  const [, claimText] = clockTimes(claim);
  const unitClauses = goSplit(sentenceBreak, softJoin(unitText));
  for (const c of goSplit(sentenceBreak, softJoin(claimText))) {
    for (const m of numbersIn(c, claimLanguage, verbatim)) {
      const key = m.reading.key;
      const mine = periods(c, claimLanguage, key, verbatim);
      if (mine.size === 0) continue;
      let matched = false;
      let agrees = false;
      let other: [string, string] | null = null;
      for (const uc of unitClauses) {
        if (!numbersIn(uc, eu.language).some((um) => um.reading.key === key)) continue;
        const theirs = periods(uc, eu.language, key);
        if (theirs.size === 0) {
          agrees = true; // the unit states the value without a period here
          continue;
        }
        matched = true;
        for (const q of mine) if (sameQuantityIn(q, theirs)) agrees = true;
        if (other === null) {
          for (const q of theirs) {
            const qs = qsplit(q);
            if (other === null || cmpGo(qs[0], other[0]) < 0) other = qs;
          }
        }
      }
      if (matched && !agrees) {
        let claimed: [string, string] | null = null;
        for (const q of mine) {
          const qs = qsplit(q);
          if (claimed === null || cmpGo(qs[0], claimed[0]) < 0) claimed = qs;
        }
        const cl = claimed ?? ["", ""];
        const ot = other ?? ["", ""];
        return `value guard: ${trimPrefix(key, "?")} for ${cl[0]} ${cl[1]} where the passage says ${ot[0]} ${ot[1]}`;
      }
    }
  }
  return "";
}

// ─── subject swap, through the glossary ─────────────────────────────────────

const MODAL_WORDS: ReadonlySet<string> = new Set([
  "must", "may", "can", "will", "shall", "should", "moet", "mag", "kan", "zal", "dient",
]);

const SEPARABLE: ReadonlySet<string> = new Set(SEPARABLE_PARTICLES);

/** subjectSwapGuard: see the file comment. */
export function subjectSwapGuard(claim: string, claimLanguage: string, eu: EvidenceUnit, cfg: GuardConfig): string {
  const cross =
    claimLanguage !== "" && eu.language !== "" && primaryLanguage(claimLanguage) !== primaryLanguage(eu.language);
  if (!cross || glossEmpty(cfg.gloss)) return "";
  const gloss = glossIdx(cfg.gloss) ?? new Map<string, string[][]>();
  const forms = (w: string): string[][] => gloss.get(w) ?? [];
  const sentences: string[][] = [];
  for (const s of goSplit(sentenceBreak, softJoin(eu.text))) {
    const toks = tokenizeV2(s);
    if (toks.length > 0) sentences.push(toks);
  }
  const claimTokens = tokenizeV2(claim);
  const subjectOf = (toks: readonly string[], verb: number): string[] | null => {
    if (toks.length > 1) {
      const modal = MODAL_WORDS.has(toks[2 % toks.length] as string);
      if (
        PARTY_DETERMINERS.has(toks[0] as string) &&
        partyWord(toks[1] as string) &&
        (verb === 2 || (verb === 3 && modal))
      ) {
        return [toks[1] as string];
      }
    }
    if (primaryLanguage(eu.language) === "nl" && verb + 2 < toks.length) {
      if (PARTY_DETERMINERS.has(toks[verb + 1] as string) && partyWord(toks[verb + 2] as string)) {
        return [toks[verb + 2] as string];
      }
    }
    return null;
  };
  const subjects = new Set<string>();
  for (const toks of sentences) {
    if (toks.length > 2 && PARTY_DETERMINERS.has(toks[0] as string) && partyWord(toks[1] as string)) {
      subjects.add(toks[1] as string);
    }
    for (let j = 0; j < toks.length; j++) {
      const subj = subjectOf(toks, j);
      if (subj !== null && j > 0 && gloss.has(toks[j] as string)) subjects.add(subj[0] as string);
    }
  }
  const classes = glossClass(cfg.gloss);
  const parties: string[] = [];
  for (const p of subjects) {
    const c = classes.get(p);
    if (c !== undefined && c !== "party" && c !== "group" && !actorTerm(p, cfg.actors)) continue;
    parties.push(p);
  }
  parties.sort(cmpGo);
  const seps = glossSep(cfg.gloss);
  const sepKeys = glossSeps(cfg.gloss);
  const verbMatches = (toks: readonly string[], j: number, claimVerb: string): boolean => {
    const t = toks[j] as string;
    if (isStopword(t) || !partyWord(t)) return false;
    const p = seps.get(t) ?? "";
    if (p !== "") {
      let found = false;
      for (let k = j + 1; k < toks.length; k++) if (toks[k] === p) found = true;
      if (!found) return false;
    }
    for (const vf of forms(t)) if (vf.length === 1 && vf[0] === claimVerb) return true;
    for (let k = j + 1; k < toks.length; k++) {
      if (!SEPARABLE.has(toks[k] as string)) continue;
      const stem = trimSuffixGo(trimSuffixGo(t, "t"), "en");
      for (const sk of sepKeys.get(toks[k] as string) ?? []) {
        if (!sk.rest.startsWith(stem) || byteLen(stem) < 3) continue;
        for (const vf of sk.trs) if (vf.length === 1 && vf[0] === claimVerb) return true;
      }
    }
    return false;
  };
  const verbAfter = (from: number): string => {
    let v = from;
    while (v < claimTokens.length && MODAL_WORDS.has(claimTokens[v] as string)) v++;
    return v >= claimTokens.length ? "" : (claimTokens[v] as string);
  };
  const check = (party: string, reader: boolean, claimVerb: string): string => {
    let agrees = false;
    let other = "";
    for (const toks of sentences) {
      for (let j = 0; j < toks.length; j++) {
        if (!verbMatches(toks, j, claimVerb)) continue;
        const subj = subjectOf(toks, j);
        if (subj === null) continue;
        const s0 = subj[0] as string;
        if (reader && actorTerm(s0, cfg.actors)) agrees = true;
        else if (reader && !isParty(s0, cfg)) agrees = true;
        else if (!reader && (s0 === party || sameActorClass(s0, party, cfg.actors))) agrees = true;
        else if (other === "") other = s0;
      }
    }
    if (!agrees && other !== "") {
      return `role guard: ${goQuote(party)} ${claimVerb} where the passage says ${goQuote(other)} does`;
    }
    return "";
  };
  for (const p of parties) {
    for (const f of forms(p)) {
      for (const sp of findSpans(claimTokens, f)) {
        const claimVerb = verbAfter(sp.end);
        if (claimVerb !== "") {
          const reason = check(p, false, claimVerb);
          if (reason !== "") return reason;
        }
      }
    }
  }
  for (let i = 0; i < claimTokens.length; i++) {
    const t = claimTokens[i] as string;
    if (!READER_SUBJECTS.has(t)) continue;
    const claimVerb = verbAfter(i + 1);
    if (claimVerb !== "") {
      const reason = check(t, true, claimVerb);
      if (reason !== "") return reason;
    }
  }
  return "";
}

function trimSuffixGo(s: string, suffix: string): string {
  return s.endsWith(suffix) ? s.slice(0, s.length - suffix.length) : s;
}

function sameActorClass(a: string, b: string, lexicon: ActorLexicon): boolean {
  for (const terms of Object.values(lexicon.actors)) if (hasTerm(terms, a) && hasTerm(terms, b)) return true;
  return false;
}

const READER_SUBJECTS: ReadonlySet<string> = new Set(["you", "je", "jij", "u"]);

/** The glossary classes the noun as a party or a group. */
function isParty(noun: string, cfg: GuardConfig): boolean {
  const c = glossClass(cfg.gloss).get(noun);
  return c === "party" || c === "group";
}
