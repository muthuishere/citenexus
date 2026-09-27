// Guards for the MODEL path — port of golang/answer/verify_guards_model.go.
//
// Swaps an NLI model admits with P(entailment) ≈ 0.999 that no threshold stops.
// Each is deterministic, table-driven, and can only refuse. They run inside
// guards() on every quote and model admission.

import { align } from "../gate/verify-v2.js";
import { isStopword } from "../gate/gate.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { Rat, cmpGo, findAllStrings, goLower, goQuote, goSplit, ratKey, replaceAll, runeLen, sortedGo } from "./gotext.js";
import { type VerbatimNumbers, clockTimes, moneyRates, readWith, verbatimIn } from "./numbers.js";
import { clauseBreak, ordinalWords } from "./verify-guards.js";

// ─── polarity-swap guard ─────────────────────────────────────────────────────

/** Single-word substitutions that flip a claim's polarity, both directions. */
const POLARITY_SWAPS: ReadonlyMap<string, readonly string[]> = new Map([
  ["een", ["geen"]], ["geen", ["een"]],
  ["wel", ["niet"]], ["niet", ["wel"]],
  ["altijd", ["nooit"]], ["nooit", ["altijd"]],
  ["always", ["never"]], ["never", ["always"]],
  ["a", ["no"]], ["an", ["no"]], ["no", ["a", "an"]],
  ["toegestaan", ["verboden"]], ["verboden", ["toegestaan"]],
  ["allowed", ["forbidden", "prohibited"]], ["forbidden", ["allowed"]], ["prohibited", ["allowed"]],
  ["permitted", ["prohibited"]], ["verplicht", ["optioneel"]], ["optioneel", ["verplicht"]],
  ["required", ["optional"]], ["optional", ["required"]],
]);

/** A claim that is the passage with ONE polarity word swapped. */
export function polaritySwapGuard(claim: string, passage: string): string {
  const claimTokens = tokenizeV2(claim);
  const passageTokens = tokenizeV2(passage);
  const aligns = (tokens: readonly string[]): boolean => align(tokens, passageTokens) !== null;
  if (claimTokens.length === 0 || aligns(claimTokens)) return "";
  for (let i = 0; i < claimTokens.length; i++) {
    const t = claimTokens[i] as string;
    for (const swap of POLARITY_SWAPS.get(t) ?? []) {
      const variant = [...claimTokens.slice(0, i), swap, ...claimTokens.slice(i + 1)];
      if (aligns(variant)) {
        return `negation guard: the claim says ${goQuote(t)} where the passage says ${goQuote(swap)}`;
      }
    }
  }
  return "";
}

// ─── unit guard ──────────────────────────────────────────────────────────────

/** A unit word (NL + EN, with abbreviations) to its class. */
export const TIME_UNITS: ReadonlyMap<string, string> = new Map([
  ["day", "day"], ["days", "day"], ["dag", "day"], ["dagen", "day"],
  ["kalenderdag", "day"], ["kalenderdagen", "day"],
  ["werkdag", "workday"], ["werkdagen", "workday"],
  ["week", "week"], ["weeks", "week"], ["weken", "week"], ["wk", "week"], ["wkn", "week"],
  ["month", "month"], ["months", "month"], ["maand", "month"], ["maanden", "month"], ["mnd", "month"],
  ["year", "year"], ["years", "year"], ["jaar", "year"], ["jaren", "year"], ["jr", "year"], ["yr", "year"], ["yrs", "year"],
  ["hour", "hour"], ["hours", "hour"], ["uur", "hour"], ["uren", "hour"], ["hr", "hour"], ["hrs", "hour"],
  ["minute", "minute"], ["minutes", "minute"], ["minuut", "minute"], ["minuten", "minute"], ["min", "minute"],
  ["jarig", "year"], ["jarige", "year"], ["urig", "hour"], ["urige", "hour"], ["daags", "day"], ["daagse", "day"],
]);

/** Precede "day(s)" in English and change its class. */
const UNIT_MODIFIERS: ReadonlyMap<string, string> = new Map([
  ["working", "workday"], ["business", "workday"], ["calendar", "day"],
]);

/** Spelled-out values a policy writes before a unit. */
export const NUMBER_WORDS: ReadonlyMap<string, string> = new Map([
  ["zero", "0"], ["one", "1"], ["two", "2"], ["three", "3"], ["four", "4"], ["five", "5"], ["six", "6"],
  ["seven", "7"], ["eight", "8"], ["nine", "9"], ["ten", "10"], ["eleven", "11"], ["twelve", "12"],
  ["thirteen", "13"], ["fourteen", "14"], ["fifteen", "15"], ["sixteen", "16"], ["seventeen", "17"],
  ["eighteen", "18"], ["nineteen", "19"], ["twenty", "20"], ["thirty", "30"], ["forty", "40"],
  ["fifty", "50"], ["sixty", "60"],
  ["nul", "0"], ["een", "1"], ["één", "1"], ["twee", "2"], ["drie", "3"], ["vier", "4"], ["vijf", "5"],
  ["zes", "6"], ["zeven", "7"], ["acht", "8"], ["negen", "9"], ["tien", "10"], ["elf", "11"],
  ["twaalf", "12"], ["dertien", "13"], ["veertien", "14"], ["vijftien", "15"], ["zestien", "16"],
  ["zeventien", "17"], ["achttien", "18"], ["negentien", "19"], ["twintig", "20"], ["dertig", "30"],
  ["veertig", "40"], ["vijftig", "50"], ["zestig", "60"],
]);

/** golang unitScan: `[0-9]+(?:[.,][0-9]+)*|½|\p{L}+`. */
export const UNIT_SCAN = /[0-9]+(?:[.,][0-9]+)*|½|\p{L}+/dgu;

/** Time units inside a Dutch compound, longest first. */
const UNIT_SUFFIXES: readonly (readonly [string, string])[] = [
  ["werkdagen", "workday"], ["werkdag", "workday"],
  ["maanden", "month"], ["dagen", "day"], ["weken", "week"], ["jaren", "year"],
  ["maand", "month"], ["jaar", "year"], ["uren", "hour"], ["dag", "day"], ["uur", "hour"],
];

const WEEKDAYS: ReadonlySet<string> = new Set([
  "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag",
]);

/** A token's time-unit class: [class, compound, ok]. */
export function unitOf(token: string): [string, boolean, boolean] {
  const c = TIME_UNITS.get(token);
  if (c !== undefined) return [c, false, true];
  if (runeLen(token) < 6) return ["", false, false];
  if (WEEKDAYS.has(token)) return ["", false, false];
  for (const [suffix, cls] of UNIT_SUFFIXES) {
    if (token.endsWith(suffix) && token !== suffix) return [cls, true, true];
  }
  return ["", false, false];
}

/** May sit between a number and its unit when several numbers share one. */
const QUANTITY_LINKS: ReadonlySet<string> = new Set([
  "respectievelijk", "resp", "en", "of", "tot", "à", "and", "or", "to",
]);

/** [value key, isNumber] of a unitScan token. */
export function numberValue(token: string, language: string, verbatim?: VerbatimNumbers): [string, boolean] {
  if (token === "½") return ["0.5", true];
  const c = token.charCodeAt(0);
  if (c >= 48 && c <= 57) return [readWith(token, false, language, verbatim).key, true];
  return numberWordValue(token);
}

/** A quantity (value key, unit class) as one set key. */
export function qkey(value: string, cls: string): string {
  return `${value}\u0000${cls}`;
}
export function qsplit(k: string): [string, string] {
  const i = k.indexOf("\u0000");
  return [k.slice(0, i), k.slice(i + 1)];
}

/** The (value key, unit class) pairs in text (golang quantities). */
export function quantities(text: string, language: string, verbatim?: VerbatimNumbers): Set<string> {
  [, text] = clockTimes(text); // "7.30 uur" is a time of day, not 7.3 hours
  [, text] = moneyRates(text, language, verbatim); // "€ 150 per maand" is a price, not 150 months
  const tokens = findAllStrings(UNIT_SCAN, goLower(text));
  const out = new Set<string>();
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i] as string;
    if (t === "halfjaar") {
      out.add(qkey("6", "month"));
      continue;
    }
    if (t === "half") {
      let j = i + 1;
      if (j < tokens.length && tokens[j] === "a") j++;
      if (j < tokens.length && (tokens[j] === "jaar" || tokens[j] === "year")) out.add(qkey("6", "month"));
      continue;
    }
    const ord = ordinalWords.get(t);
    if (ord !== undefined && i + 1 < tokens.length) {
      const [cls, compound, ok] = unitOf(tokens[i + 1] as string);
      if (ok && compound && cls === "year") out.add(qkey(ord, "year"));
      continue;
    }
    let [value, isNumber] = numberValue(t, language, verbatim);
    if (!isNumber) continue;
    let j = i + 1;
    if (j < tokens.length) {
      const [v, n] = numberValue(tokens[j] as string, language, verbatim);
      if (n && v === value) j++;
    }
    while (j + 1 < tokens.length && j - i <= 6) {
      if (!QUANTITY_LINKS.has(tokens[j] as string)) break;
      let skip = 0;
      if (RANGE_BOUND_WORDS.has(tokens[j + 1] as string) && j + 2 < tokens.length) skip = 1;
      const [linked, n] = numberValue(tokens[j + 1 + skip] as string, language, verbatim);
      if (!n) break;
      j += 2 + skip;
      if (j < tokens.length) {
        const [v, n2] = numberValue(tokens[j] as string, language, verbatim);
        if (n2 && v === linked) j++; // "drie (3)" after the link
      }
    }
    if (j >= tokens.length) continue;
    let [cls, , ok] = unitOf(tokens[j] as string);
    const mod = UNIT_MODIFIERS.get(tokens[j] as string);
    if (mod !== undefined && j + 1 < tokens.length) {
      if (unitOf(tokens[j + 1] as string)[0] === "day") {
        cls = mod;
        ok = true;
      }
    }
    if (!ok && j + 1 < tokens.length) {
      if (!numberValue(tokens[j] as string, language, verbatim)[1]) {
        const c = TIME_UNITS.get(tokens[j + 1] as string);
        if (c !== undefined) {
          cls = c;
          ok = true;
          if (tokens[j] === "half" || tokens[j] === "halve") {
            const v = Rat.parse(value);
            if (v !== null) value = ratKey(v.mul(new Rat(1n, 2n)));
          }
        }
      }
    }
    if (ok) out.add(qkey(value, cls));
  }
  return out;
}

/** The same period in the other unit, when exact: v years <-> 12v months. */
export function equivalentQuantity(q: string): [string, boolean] {
  const [value, cls] = qsplit(q);
  const v = Rat.parse(value);
  if (v === null) return [q, false];
  if (cls === "year") return [qkey(ratKey(v.mul(new Rat(12n))), "month"), true];
  if (cls === "month") return [qkey(ratKey(v.quo(new Rat(12n))), "year"), true];
  return [q, false];
}

/** A SWAP of a quantity: same number, other unit; or same unit, other number. */
export function unitGuard(claim: string, claimLanguage: string, passage: string, passageLanguage: string): string {
  [, claim] = clockTimes(claim); // a clock time is never a duration
  [, passage] = clockTimes(passage);
  // A number the claim copies from the passage keeps the passage's reading
  // (ADR-0015 amendment).
  const verbatim = verbatimIn(passage, passageLanguage);
  const [claimRates] = moneyRates(claim, claimLanguage, verbatim);
  const [passageRates] = moneyRates(passage, passageLanguage);
  const passageSorted = sortedPairs(passageRates);
  for (const r of sortedPairs(claimRates)) {
    if (passageRates.has(r)) continue;
    const [rv, rc] = qsplit(r);
    for (const p of passageSorted) {
      const [pv, pc] = qsplit(p);
      if (pv === rv && pc !== rc && !samePeriodFamily(pc, rc)) {
        return `unit guard: ${rv} per ${rc} where the passage says ${pv} per ${pc}`;
      }
    }
  }
  const have = quantities(passage, passageLanguage);
  const claimed = sortedPairs(quantities(claim, claimLanguage, verbatim));
  for (const q of claimed) {
    if (have.has(q)) continue;
    if (sameQuantityIn(q, have)) continue;
    const [qv, qc] = qsplit(q);
    const sameValue: string[] = [];
    const sameUnit: string[] = [];
    for (const p of have) {
      const [pv, pc] = qsplit(p);
      if (pv === qv) sameValue.push(pc);
      if (pc === qc) sameUnit.push(pv);
    }
    if (sameValue.length > 0) {
      return `unit guard: ${qv} ${qc} where the passage says ${qv} ${sortedStrings(sameValue).join("/")}`;
    }
    if (sameUnit.length > 0) {
      return `unit guard: ${qv} ${qc} where the passage says ${sortedStrings(sameUnit).join("/")} ${qc}`;
    }
  }
  return "";
}

export function sortedStrings(xs: readonly string[]): string[] {
  return sortedGo(new Set(xs));
}

// ─── qualifier / role guard ──────────────────────────────────────────────────

interface QualifierSide {
  nl: readonly string[];
  en: readonly string[];
}
type QualifierPairSides = readonly [QualifierSide, QualifierSide];

const QUALIFIER_PAIRS: readonly QualifierPairSides[] = [
  [{ nl: ["bruto"], en: ["gross"] }, { nl: ["netto"], en: ["net"] }],
  [{ nl: ["werkgever"], en: ["employer"] }, { nl: ["werknemer"], en: ["employee"] }],
  [{ nl: ["vóór", "voordat"], en: ["before"] }, { nl: ["na", "ná", "nadat"], en: ["after"] }],
  [{ nl: ["eerder"], en: ["earlier"] }, { nl: ["later"], en: ["later"] }],
  [{ nl: ["minimaal"], en: ["minimum"] }, { nl: ["maximaal"], en: ["maximum"] }],
  [
    { nl: ["schriftelijk", "schriftelijke"], en: ["written", "writing"] },
    { nl: ["mondeling", "mondelinge"], en: ["oral", "orally", "verbally"] },
  ],
];

export function matchesForm(token: string, form: string): boolean {
  if (runeLen(form) >= 5) return token.includes(form);
  return token === form;
}

export function anyForm(token: string, forms: readonly string[]): boolean {
  for (const form of forms) if (matchesForm(token, form)) return true;
  return false;
}

function formsIn(q: QualifierSide, language: string): readonly string[] {
  return language === "nl" ? q.nl : q.en;
}

/** Function words that carry no locating signal, NL + EN. */
export const CONTEXT_STOP: ReadonlySet<string> = new Set([
  "de", "het", "een", "en", "van", "in", "op", "te", "dat",
  "die", "is", "zijn", "voor", "met", "aan", "bij", "of",
  "als", "ook", "om", "naar", "door", "over", "tot", "uit",
  "je", "jouw", "uw", "wordt", "worden",
]);

const QUALIFIER_WINDOW = 5;

/** Tokenize text clause by clause. */
export function clauseTokens(text: string): string[][] {
  const out: string[][] = [];
  for (const clause of goSplit(clauseBreak, softJoin(text))) {
    const tokens = tokenizeV2(clause);
    if (tokens.length > 0) out.push(tokens);
  }
  return out;
}

/** A line break that does not end a sentence — a PDF wrap. */
const SOFT_LINE_BREAK = new RegExp(`([^.!?:;\\n])[ \\t]*\\n[ \\t]*([^\\n\\-*•·0-9])`, "dgu");

export function softJoin(text: string): string {
  return replaceAll(SOFT_LINE_BREAK, text, "$1 $2");
}

function window(tokens: readonly string[], i: number, pair: QualifierPairSides): Set<string> {
  const out = new Set<string>();
  for (let k = i - QUALIFIER_WINDOW; k <= i + QUALIFIER_WINDOW; k++) {
    if (k < 0 || k >= tokens.length || k === i) continue;
    const t = tokens[k] as string;
    if (isStopword(t) || isPairForm(t, pair)) continue;
    if (CONTEXT_STOP.has(t)) continue;
    out.add(t);
  }
  return out;
}

function isPairForm(t: string, pair: QualifierPairSides): boolean {
  for (const side of pair) if (anyForm(t, side.nl) || anyForm(t, side.en)) return true;
  return false;
}

/** One side of a closed pair where the passage, at the matching place, carries
 * the other. SAME LANGUAGE ONLY. */
export function qualifierGuard(claim: string, passage: string): string {
  const passageClauses = clauseTokens(passage);
  for (const pair of QUALIFIER_PAIRS) {
    for (const claimToks of clauseTokens(claim)) {
      for (let i = 0; i < claimToks.length; i++) {
        const t = claimToks[i] as string;
        for (let s = 0; s < 2; s++) {
          for (const lang of ["nl", "en"]) {
            const same = formsIn(pair[s] as QualifierSide, lang);
            const other = formsIn(pair[1 - s] as QualifierSide, lang);
            if (!anyForm(t, same) || anyForm(t, other)) continue;
            if (namesBoth(claimToks, i, other)) continue;
            const first = pair[0].en[0];
            if (first === "before" || first === "earlier") {
              if (relationalSwap(claimToks, i, passageClauses, same, other)) {
                return `qualifier guard: the claim says ${goQuote(t)} where the passage says ${other.join("/")}`;
              }
              continue;
            }
            const context = window(claimToks, i, pair);
            let bestSame = -1;
            let bestOther = -1;
            let sawSame = false;
            let sawOther = false;
            for (const passageTokens of passageClauses) {
              for (let j = 0; j < passageTokens.length; j++) {
                const p = passageTokens[j] as string;
                const isSame = anyForm(p, same);
                const isOther = anyForm(p, other);
                if (isSame === isOther) continue;
                let score = 0;
                for (const w of window(passageTokens, j, pair)) if (context.has(w)) score++;
                if (isSame) {
                  sawSame = true;
                  if (score > bestSame) bestSame = score;
                } else {
                  sawOther = true;
                  if (score > bestOther) bestOther = score;
                }
              }
            }
            if (sawOther && (!sawSame || bestOther > bestSame)) {
              return `qualifier guard: the claim says ${goQuote(t)} where the passage says ${other.join("/")}`;
            }
          }
        }
      }
    }
  }
  return "";
}

function namesBoth(tokens: readonly string[], i: number, other: readonly string[]): boolean {
  for (let k = i - QUALIFIER_WINDOW; k <= i + QUALIFIER_WINDOW; k++) {
    if (k >= 0 && k < tokens.length && k !== i && anyForm(tokens[k] as string, other)) return true;
  }
  return false;
}

function nextContent(tokens: readonly string[], i: number): string {
  for (let k = i + 1; k < tokens.length; k++) {
    const t = tokens[k] as string;
    if (isStopword(t)) continue;
    if (CONTEXT_STOP.has(t)) continue;
    return t;
  }
  return "";
}

function relationalSwap(
  claimToks: readonly string[],
  i: number,
  passageClauses: readonly (readonly string[])[],
  same: readonly string[],
  other: readonly string[],
): boolean {
  const target = nextContent(claimToks, i);
  if (target === "") return false;
  let sawOther = false;
  for (const tokens of passageClauses) {
    for (let j = 0; j < tokens.length; j++) {
      const p = tokens[j] as string;
      if (nextContent(tokens, j) !== target) continue;
      if (anyForm(p, same)) return false;
      if (anyForm(p, other)) sawOther = true;
    }
  }
  return sawOther;
}

// ─── scope guard ─────────────────────────────────────────────────────────────

const DURING_WORDS: ReadonlySet<string> = new Set(["during", "throughout", "tijdens", "gedurende"]);

const UNIVERSALS: ReadonlySet<string> = new Set([
  "any", "all", "every", "each", "alle", "elk", "elke", "ieder", "iedere",
]);

function duringScopes(text: string): [boolean, boolean] {
  const tokens = tokenizeV2(text);
  let universal = false;
  let specific = false;
  for (let i = 0; i < tokens.length; i++) {
    if (!DURING_WORDS.has(tokens[i] as string) || i + 1 >= tokens.length) continue;
    let next = tokens[i + 1] as string;
    if ((next === "the" || next === "de" || next === "het") && i + 2 < tokens.length) next = tokens[i + 2] as string;
    if (UNIVERSALS.has(next)) universal = true;
    else specific = true;
  }
  return [universal, specific];
}

/** The passage attaches a fact to a SPECIFIC period and the claim widens it. */
export function scopeGuard(claim: string, passage: string): string {
  const [claimUniversal] = duringScopes(claim);
  if (!claimUniversal) return "";
  const [passageUniversal, passageSpecific] = duringScopes(passage);
  if (passageSpecific && !passageUniversal) {
    return "scope guard: the claim widens a specific period in the passage to every period";
  }
  return "";
}

/** Quantity keys sorted by (value, unit) in Go string order. */
export function sortedPairs(set: Iterable<string>): string[] {
  return [...set].sort((a, b) => {
    const [av, ac] = qsplit(a);
    const [bv, bc] = qsplit(b);
    return av !== bv ? cmpGo(av, bv) : cmpGo(ac, bc);
  });
}

/** q, or the same period in another unit, is in have. */
export function sameQuantityIn(q: string, have: ReadonlySet<string>): boolean {
  if (have.has(q)) return true;
  const [eq, ok] = equivalentQuantity(q);
  if (ok && have.has(eq)) return true;
  const [value, cls] = qsplit(q);
  const v = Rat.parse(value);
  if (v === null) return false;
  if (cls === "year") return have.has(qkey(ratKey(v.mul(new Rat(52n))), "week"));
  if (cls === "week") {
    const y = v.quo(new Rat(52n));
    return have.has(qkey(ratKey(y), "year")) && y.isInt();
  }
  return false;
}

/** day and workday are not told apart for a rate. */
function samePeriodFamily(a: string, b: string): boolean {
  return (a === "day" || a === "workday") && (b === "day" || b === "workday");
}

const DUTCH_UNITS: ReadonlyMap<string, number> = new Map([
  ["een", 1], ["één", 1], ["twee", 2], ["drie", 3], ["vier", 4], ["vijf", 5], ["zes", 6], ["zeven", 7], ["acht", 8], ["negen", 9],
]);
const DUTCH_TEENS: ReadonlyMap<string, number> = new Map([
  ["tien", 10], ["elf", 11], ["twaalf", 12], ["dertien", 13], ["veertien", 14], ["vijftien", 15],
  ["zestien", 16], ["zeventien", 17], ["achttien", 18], ["negentien", 19],
]);
const DUTCH_TENS: ReadonlyMap<string, number> = new Map([
  ["twintig", 20], ["dertig", 30], ["veertig", 40], ["vijftig", 50], ["zestig", 60],
  ["zeventig", 70], ["tachtig", 80], ["negentig", 90],
]);

/** numberWords first, then Dutch compounds ("vijfentwintig", "tweeduizend"). */
export function numberWordValue(word: string): [string, boolean] {
  const v = NUMBER_WORDS.get(word);
  if (v !== undefined) return [v, true];
  const [n, ok] = parseDutchNumber(word);
  if (ok && n > 0) return [String(n), true];
  return ["", false];
}

function cut(s: string, sep: string): [string, string, boolean] {
  const i = s.indexOf(sep);
  if (i < 0) return [s, "", false];
  return [s.slice(0, i), s.slice(i + sep.length), true];
}

function parseDutchNumber(w: string): [number, boolean] {
  if (w === "") return [0, false];
  {
    const [head, tail, ok] = cut(w, "duizend");
    if (ok) {
      let mult = 1;
      if (head !== "") {
        const [m, ok2] = parseDutchNumber(head);
        if (!ok2) return [0, false];
        mult = m;
      }
      let rest = 0;
      if (tail !== "") {
        const [r, ok2] = parseDutchNumber(tail);
        if (!ok2) return [0, false];
        rest = r;
      }
      return [mult * 1000 + rest, true];
    }
  }
  {
    const [head, tail, ok] = cut(w, "honderd");
    if (ok) {
      let mult = 1;
      if (head !== "") {
        const m = DUTCH_UNITS.get(head);
        if (m === undefined) return [0, false];
        mult = m;
      }
      let rest = 0;
      if (tail !== "") {
        const [r, ok2] = parseDutchNumber(tail);
        if (!ok2 || r >= 100) return [0, false];
        rest = r;
      }
      return [mult * 100 + rest, true];
    }
  }
  const u = DUTCH_UNITS.get(w);
  if (u !== undefined) return [u, true];
  const te = DUTCH_TEENS.get(w);
  if (te !== undefined) return [te, true];
  const tn = DUTCH_TENS.get(w);
  if (tn !== undefined) return [tn, true];
  for (const link of ["ën", "en"]) {
    for (const [tens, tv] of DUTCH_TENS) {
      const suffix = link + tens;
      if (w.endsWith(suffix)) {
        const uv = DUTCH_UNITS.get(w.slice(0, w.length - suffix.length));
        if (uv !== undefined) return [uv + tv, true];
      }
    }
  }
  return [0, false];
}

/** May precede the second number of a range. */
export const RANGE_BOUND_WORDS: ReadonlySet<string> = new Set([
  "maximaal", "minimaal", "hooguit", "maximum", "minimum", "most", "least",
]);
