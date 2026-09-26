// Deterministic guards for model-admitted claims, and quote extraction — port of
// golang/answer/verify_guards.go.
//
// A SupportChecker may admit a claim the token gate could not verify (a
// translation, a paraphrase). These guards run on every such admission and the
// model cannot override them: numbers, negation and names are exactly where an
// entailment model is weakest. Each guard can only REFUSE.

import { align, MAX_SINGLE_GAP, POLARITY_MARKERS } from "../gate/verify-v2.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import {
  GS,
  Rat,
  containsAny,
  findAll,
  findAllStrings,
  goFields,
  goLower,
  goQuote,
  goSplit,
  goTrim,
  goTrimRight,
  isDigitRune,
  isLetterRune,
  isUpperRune,
  matches,
  ratKey,
  runes,
  startsWithAny,
  trimPrefix,
  trimSuffix,
} from "./gotext.js";
import {
  clockTimes,
  dateKeyString,
  datesIn,
  numbersIn,
  sameDate,
  type NumberMatch,
} from "./numbers.js";
import {
  UNIT_SCAN,
  numberValue,
  numberWordValue,
  polaritySwapGuard,
  qualifierGuard,
  scopeGuard,
  softJoin,
  unitGuard,
  unitOf,
} from "./verify-guards-model.js";
import type { EvidenceUnit } from "./verify-answer.js";
import type { ActorLexicon } from "./verify-roles.js";
import { roleGuard } from "./verify-roles.js";
import { relationGuard } from "./verify-relations.js";
import { exclusionGuard } from "./verify-exclusions.js";
import { hedgeGuard } from "./verify-hedges.js";
import { verbPairGuard, type VerbPair } from "./verify-verbpairs.js";
import { definitionGuard, type Definition } from "./verify-definitions.js";
import { subtypeGuard, type SubtypeHead } from "./verify-subtypes.js";
import { conditionGuard } from "./verify-conditions.js";
import { conjunctTokenGuard } from "./verify-conjuncts.js";
import { qualifierPairGuard, type QualifierPair } from "./verify-qualifier-pairs.js";
import { partySwapGuard, subjectSwapGuard, valueRowGuard, findSpans } from "./verify-parties.js";
import type { PreparedGlossary } from "./glossary.js";

/**
 * numberGuard: every number in the claim is a number in the passage, compared
 * by ADR-0015 key, each side read in ITS OWN declared language. Spelled-out
 * passage numbers count ("één vakantiedag"), minus "een"; ordinal words satisfy
 * only an ordinal claim number.
 */
export function numberGuard(claim: string, claimLanguage: string, passage: string, passageLanguage: string): string {
  const [claimClocks, claim1] = clockTimes(claim);
  const [passageClocks, passage1] = clockTimes(passage);
  const [claimDates, claim2] = datesIn(claim1, claimLanguage);
  const [passageDates, passage2] = datesIn(passage1, passageLanguage);
  claim = claim2;
  passage = passage2;
  for (const cd of claimDates) {
    if (!passageDates.some((pd) => sameDate(cd, pd))) {
      return `number guard: ${dateKeyString(cd)} is not in the passage`;
    }
  }
  for (const k of [...claimClocks].sort()) {
    if (!passageClocks.has(k)) return `number guard: ${trimPrefix(k, "clock:")} is not in the passage`;
  }
  const have = new Set<string>();
  for (const m of numbersIn(passage, passageLanguage)) {
    have.add(centsAsEuros(m));
    if (ORDINAL_SUFFIXES.has(m.unit) && m.attached) have.add("ord:" + m.reading.key);
  }
  for (const word of findAllStrings(UNIT_SCAN, goLower(passage))) {
    const [value, ok] = numberWordValue(word);
    if (ok && word !== "een") have.add(value);
    const ord = ordinalWords.get(word);
    if (ord !== undefined) have.add("ord:" + ord);
  }
  for (const m of numbersIn(claim, claimLanguage)) {
    let key = centsAsEuros(m);
    if (ORDINAL_SUFFIXES.has(m.unit) && m.attached) key = "ord:" + key;
    if (!have.has(key)) {
      return `number guard: ${trimPrefix(trimPrefix(key, "ord:"), "?")} is not in the passage`;
    }
  }
  return countConflict(claim, passage, passageLanguage);
}

/** A number word in the claim before a noun the passage counts only with other values. */
function countConflict(claim: string, passage: string, passageLanguage: string): string {
  const words = findAllStrings(UNIT_SCAN, goLower(claim));
  const ptoks = findAllStrings(UNIT_SCAN, goLower(passage));
  for (let i = 0; i < words.length; i++) {
    const word = words[i] as string;
    const [value, ok] = numberWordValue(word);
    if (!ok || word === "een" || word === "one" || i + 1 >= words.length) continue;
    const noun = words[i + 1] as string;
    if (COUNT_FUNCTION_WORDS.has(noun)) continue;
    if (unitOf(noun)[2]) continue;
    if (numberValue(noun, passageLanguage)[1]) continue;
    const span = [noun];
    if (noun.endsWith("e") && i + 2 < words.length) span.push(words[i + 2] as string);
    const others: string[] = [];
    let agrees = false;
    for (let k = 0; k + span.length < ptoks.length; k++) {
      if (!equalTokens(ptoks.slice(k + 1, k + 1 + span.length), span) || ptoks[k] === "een" || ptoks[k] === "one") {
        continue;
      }
      const [pv, isNumber] = numberValue(ptoks[k] as string, passageLanguage);
      if (!isNumber) continue;
      if (pv === value) agrees = true;
      else others.push(ptoks[k] as string);
    }
    if (!agrees && others.length > 0) {
      return `number guard: ${word} ${noun}, the passage says ${others[0] as string} ${noun}`;
    }
  }
  return "";
}

const COUNT_FUNCTION_WORDS: ReadonlySet<string> = new Set([
  "voor", "na", "van", "op", "in", "of", "en", "per",
  "uit", "bij", "tot", "met", "aan", "keer",
  "for", "the", "and", "or", "to", "times", "at", "by",
]);

export function equalTokens(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

/** Follow a digit to make it an ordinal: 1st, 2nd, 1e, 2de, 8ste. */
const ORDINAL_SUFFIXES: ReadonlySet<string> = new Set(["st", "nd", "rd", "th", "e", "de", "ste"]);

/** Spelled-out ordinals, NL + EN, 1–12. */
export const ordinalWords: ReadonlyMap<string, string> = new Map([
  ["eerste", "1"], ["tweede", "2"], ["derde", "3"], ["vierde", "4"], ["vijfde", "5"], ["zesde", "6"],
  ["zevende", "7"], ["achtste", "8"], ["negende", "9"], ["tiende", "10"], ["elfde", "11"], ["twaalfde", "12"],
  ["first", "1"], ["second", "2"], ["third", "3"], ["fourth", "4"], ["fifth", "5"], ["sixth", "6"],
  ["seventh", "7"], ["eighth", "8"], ["ninth", "9"], ["tenth", "10"], ["eleventh", "11"], ["twelfth", "12"],
]);

/** A claim that carries a polarity marker needs a passage that carries one. */
export function negationGuard(claim: string, passage: string): string {
  const claimTokens = tokenizeV2(claim);
  const bounded = boundMarkerPositions(claimTokens, boundDirections(tokenizeV2(passage)));
  let claimNegated = false;
  for (let i = 0; i < claimTokens.length; i++) {
    if (POLARITY_MARKERS.has(claimTokens[i] as string) && !bounded.has(i)) {
      claimNegated = true;
      break;
    }
  }
  if (!claimNegated) return "";
  for (const tok of tokenizeV2(passage)) {
    if (POLARITY_MARKERS.has(tok)) return "";
    if (NEGATIVE_WORDS.has(tok)) return "";
  }
  return "negation guard: the claim is negated and the passage is not";
}

const STRONG_REPLACER = /\*\*|__|`/g;

/**
 * The claim's capitalised words that are not in an INITIAL position, plus any
 * word mixing letters and digits or written in capitals ("R-119", "CAO").
 */
export function names(claim: string): string[] {
  const out: string[] = [];
  const plain = claim.replace(STRONG_REPLACER, "");
  let initial = true;
  for (const f of goFields(plain)) {
    if (isListMarker(f)) {
      initial = true;
      continue;
    }
    if (f === "|") {
      initial = true; // a table cell starts like a sentence
      continue;
    }
    const opensQuote = startsWithAny(f, "\"“„«([{'‘");
    let word = goTrim(f, "\"“”„«»()[]{},;:.!?'‘’|");
    word = trimSuffix(trimSuffix(word, "'s"), "’s");
    if (word.includes("-") && capitalisedParts(word).length === 0 && !containsAny(word, "0123456789")) {
      initial = false;
      continue;
    }
    const rs = runes(word);
    if (CURRENCY_CODES.has(goLower(word))) {
      initial = false;
      continue; // "EUR 2.40": a currency, not a name
    }
    if (matches(ORDINAL_TOKEN, goLower(word)) || matches(NUMBER_WITH_UNIT, goLower(word))) {
      initial = false;
      continue; // "1st", "25-jarig", "40-hour", "1/12th": a number, not a name
    }
    if (rs.length > 1) {
      let hasDigit = false;
      let hasLetter = false;
      let allUpper = true;
      for (const r of rs) {
        if (isDigitRune(r)) hasDigit = true;
        else if (isLetterRune(r)) {
          hasLetter = true;
          if (!isUpperRune(r)) allUpper = false;
        }
      }
      if ((hasLetter && hasDigit) || (hasLetter && allUpper)) out.push(word);
      else if (!initial && !opensQuote && isUpperRune(rs[0])) out.push(word);
    }
    const trimmed = goTrimRight(f, "\"”»)]}'’");
    initial =
      trimmed.endsWith(".") ||
      trimmed.endsWith("!") ||
      trimmed.endsWith("?") ||
      trimmed.endsWith(":") ||
      trimmed.endsWith(";") ||
      trimmed.endsWith("|");
  }
  return out;
}

const ORDINAL_TOKEN = /^[0-9]+(st|nd|rd|th|e|de|ste)$/dg;

/** A number joined to its unit or a fraction: "25-jarig", "40-hour", "1/12th", "9am". */
const NUMBER_WITH_UNIT =
  /^[0-9]+([.,][0-9]+)?-?(jarig|jarige|urig|urige|daags|daagse|weeks|weekse|maands|maandse|hour|hours|day|days|week|weeks|month|months|year|years)$|^[0-9]+\/[0-9]+(st|nd|rd|th|e|de|ste)?$|^[0-9]{1,2}([:.][0-5][0-9])?(am|pm)$/dg;

const LIST_MARKER = /^([-*•·–—]|#{1,6}|[0-9]{1,3}[.)]|[a-z][.)])$/dgu;

/** A bullet, heading hash or list number standing alone. */
export function isListMarker(field: string): boolean {
  return matches(LIST_MARKER, field);
}

/** Every name in the claim is present in the passage. */
export function nameGuard(claim: string, passage: string): string {
  return nameGuardWith(claim, passage, null);
}

export function nameGuardWith(
  claim: string,
  passage: string,
  aliases: Readonly<Record<string, readonly string[]>> | null | undefined,
): string {
  const name = absentName(names(claim), passage, aliases);
  if (name !== "") return `name guard: ${goQuote(name)} is not in the passage`;
  return "";
}

function aliasesOf(
  aliases: Readonly<Record<string, readonly string[]>> | null | undefined,
  key: string,
): readonly string[] | undefined {
  if (aliases === null || aliases === undefined || !Object.hasOwn(aliases, key)) return undefined;
  return aliases[key];
}

/** The first of names not present in passage ("" when all are). */
export function absentName(
  names: readonly string[],
  passage: string,
  aliases: Readonly<Record<string, readonly string[]>> | null | undefined,
): string {
  const have = new Set<string>();
  for (const tok of tokenizeV2(passage)) {
    have.add(tok);
    const folded = CALENDAR_FOLD.get(tok);
    if (folded !== undefined) have.add(folded);
  }
  const present = (tok: string): boolean => {
    if (have.has(tok)) return true;
    const folded = CALENDAR_FOLD.get(tok);
    if (folded !== undefined && have.has(folded)) return true;
    for (const alias of aliasesOf(aliases, tok) ?? []) {
      const words = tokenizeV2(alias);
      if (words.length > 0 && words.every((w) => have.has(w))) return true;
    }
    return false;
  };
  const allPresent = (text: string): boolean => tokenizeV2(text).every(present);
  for (const name of names) {
    if (name.includes("-") && !allPresent(name) && !containsAny(name, "0123456789")) {
      const parts = capitalisedParts(name);
      if (parts.length > 0 && allPresent(parts.join(" "))) continue;
    }
    const alts = aliasesOf(aliases, goLower(name));
    if (alts !== undefined) {
      let found = false;
      for (const alt of alts) {
        if (tokenizeV2(alt).every((at) => have.has(at))) {
          found = true;
          break;
        }
      }
      if (found) continue;
    }
    for (const tok of tokenizeV2(name)) {
      if (!present(tok)) return name;
    }
  }
  return "";
}

/** The hyphen-separated parts starting with a capital. */
function capitalisedParts(word: string): string[] {
  return word.split("-").filter((part) => isUpperRune(runes(part)[0]));
}

/** English month and weekday names folded to Dutch, both directions. */
export const CALENDAR_FOLD: ReadonlyMap<string, string> = (() => {
  const pairs: [string, string][] = [
    ["january", "januari"], ["february", "februari"], ["march", "maart"], ["april", "april"],
    ["may", "mei"], ["june", "juni"], ["july", "juli"], ["august", "augustus"],
    ["september", "september"], ["october", "oktober"], ["november", "november"], ["december", "december"],
    ["monday", "maandag"], ["tuesday", "dinsdag"], ["wednesday", "woensdag"], ["thursday", "donderdag"],
    ["friday", "vrijdag"], ["saturday", "zaterdag"], ["sunday", "zondag"],
  ];
  const out = new Map<string, string>();
  for (const [en, nl] of pairs) {
    out.set(en, nl);
    out.set(nl, nl);
  }
  return out;
})();

/** The caller's configuration the guards read. */
export interface GuardConfig {
  aliases: Readonly<Record<string, readonly string[]>> | null | undefined;
  actors: ActorLexicon;
  pairs: readonly QualifierPair[];
  verbs: readonly VerbPair[];
  gloss: PreparedGlossary | null;
  noDefinitions: boolean;
  docDefs: ReadonlyMap<string, Definition[]>;
  subtypes: readonly SubtypeHead[];
  /** the text is a list lead-in checked on its own (union rule) */
  fragment: boolean;
  conjunctPresence: boolean;
}

/** Every deterministic guard; the first refusal, or "". */
export function guards(claim: string, claimLanguage: string, eu: EvidenceUnit, cfg: GuardConfig): string {
  let reason = numberGuard(claim, claimLanguage, eu.text, eu.language);
  if (reason !== "") return reason;
  reason = unitGuard(claim, claimLanguage, eu.text, eu.language);
  if (reason !== "") return reason;
  for (const g of [negationGuard, clauseNegationGuard, polaritySwapGuard, qualifierGuard, scopeGuard]) {
    reason = g(claim, eu.text);
    if (reason !== "") return reason;
  }
  const steps: (() => string)[] = [
    () => roleGuard(claim, claimLanguage, eu, cfg.actors),
    () => relationGuard(claim, claimLanguage, eu, cfg.actors),
    () => truncationGuard(claim, eu.text),
    () => exclusionGuard(claim, claimLanguage, eu, cfg),
    () => hedgeGuard(claim, claimLanguage, eu, cfg),
    () => verbPairGuard(claim, claimLanguage, eu, cfg.verbs, cfg),
    () => definitionGuard(claim, claimLanguage, eu, cfg),
    () => subtypeGuard(claim, eu, cfg),
    () => conditionGuard(claim, claimLanguage, eu, cfg),
    () => conjunctTokenGuard(claim, claimLanguage, eu, cfg),
    () => qualifierPairGuard(claim, claimLanguage, eu, cfg.pairs),
    () => partySwapGuard(claim, claimLanguage, eu, cfg.actors),
    () => subjectSwapGuard(claim, claimLanguage, eu, cfg),
    () => valueRowGuard(claim, claimLanguage, eu),
  ];
  for (const step of steps) {
    reason = step();
    if (reason !== "") return reason;
  }
  return nameGuardWith(claim, eu.text + "\n" + eu.documentId, cfg.aliases);
}

/** Double-quoted spans in the common typographic styles. */
const QUOTE_PATTERN = /"([^"]+)"|“([^”]+)”|„([^”“]+)[”“]|«([^»]+)»/dgu;

/** The shortest span that counts as a quote. */
export const MIN_QUOTE_TOKENS = 3;

/** The claim's quoted spans that are long enough to anchor it. */
export function quotes(claim: string): string[] {
  const out: string[] = [];
  for (const m of findAll(QUOTE_PATTERN, claim)) {
    for (let i = 1; i <= 4; i++) {
      const g = m.group(i);
      if (g !== undefined && g !== "" && tokenizeV2(g).length >= MIN_QUOTE_TOKENS) out.push(g);
    }
  }
  return out;
}

/** Ends a clause: sentence punctuation + space/end, ", ", a dash separator, a newline. */
export const clauseBreak = new RegExp(`[.!?;:]+([${GS}]|$)|,[${GS}]|[${GS}]*[\\u2014\\u2013][${GS}]*|[${GS}]-[${GS}]|\\n`, "dgu");

/** Start a NEW coordinated clause. */
const COORDINATORS: ReadonlySet<string> = new Set(["en", "maar", "of", "want", "dus", "and", "but", "or", "so"]);

/** A polarity marker in (or just after) the matched span that the claim drops. */
export function clauseNegationGuard(claim: string, passage: string): string {
  const claimTokens = tokenizeV2(claim);
  const inClaim = new Map<string, number>();
  for (const tok of claimTokens) {
    if (POLARITY_MARKERS.has(tok)) inClaim.set(tok, (inClaim.get(tok) ?? 0) + 1);
  }
  for (const clause of goSplit(clauseBreak, passage)) {
    const clauseToks = tokenizeV2(clause);
    const span = align(claimTokens, clauseToks);
    if (span === null) continue;
    const inSpan = new Map<string, number>();
    const matched = clauseToks.slice(span.start, span.end + 1);
    for (const tok of matched) {
      if (POLARITY_MARKERS.has(tok)) inSpan.set(tok, (inSpan.get(tok) ?? 0) + 1);
    }
    for (const tok of matched) {
      const n = inSpan.get(tok);
      if (n !== undefined && (inClaim.get(tok) ?? 0) < n) {
        return `negation guard: the claim drops ${goQuote(tok)} from the matched words`;
      }
    }
    let tail = clauseToks.slice(span.end + 1);
    if (tail.length > MAX_SINGLE_GAP) tail = tail.slice(0, MAX_SINGLE_GAP);
    for (const tok of tail) {
      if (COORDINATORS.has(tok)) break;
      if (POLARITY_MARKERS.has(tok) && (inClaim.get(tok) ?? 0) === 0) {
        return `negation guard: the passage clause carries ${goQuote(tok)} after the matched words`;
      }
    }
  }
  return "";
}

/** Open a clause-internal continuation that narrows what came before it. */
const RESTRICTIVE_TAIL: ReadonlySet<string> = new Set([
  "met", "van", "voor", "tot", "boven", "onder", "bij", "aan",
  "zonder", "behalve", "uitgezonderd", "alleen", "uitsluitend",
  "mits", "tenzij", "indien", "als", "wanneer", "die", "dat", "waarvan",
  "with", "for", "above", "below", "over", "provided",
  "unless", "if", "when", "who", "that", "which",
  "without", "except", "only",
]);

/** A claim that is a cut span of a unit sentence whose restriction follows. */
export function truncationGuard(claim: string, passage: string): string {
  const claimTokens = tokenizeV2(claim);
  let restricted = "";
  for (const clause of goSplit(clauseBreak, softJoin(passage))) {
    const clauseToks = tokenizeV2(clause);
    const span = align(claimTokens, clauseToks);
    if (span === null) continue;
    const tail = clauseToks.slice(span.end + 1);
    let next = tail[0] ?? "";
    let narrows = RESTRICTIVE_TAIL.has(next);
    if (next === "up" && tail.length > 1 && tail[1] === "to") {
      narrows = true;
      next = "up to";
    }
    if (next === "in" && tail.length > 2 && tail[1] === "so" && tail[2] === "far") {
      narrows = true;
      next = "in so far as";
    }
    if (!narrows) return ""; // a clause that states the claim as it is
    if (restricted === "") restricted = next;
  }
  if (restricted === "") return "";
  return `truncation guard: the claim omits a restriction the source attaches (${goQuote(restricted)})`;
}

export const BOUND_UPPER = "upper";
export const BOUND_LOWER = "lower";

const BOUND_PHRASES: readonly { words: readonly string[]; direction: string }[] = [
  { words: ["no", "later", "than"], direction: BOUND_UPPER }, { words: ["not", "later", "than"], direction: BOUND_UPPER },
  { words: ["no", "more", "than"], direction: BOUND_UPPER }, { words: ["not", "more", "than"], direction: BOUND_UPPER },
  { words: ["at", "most"], direction: BOUND_UPPER }, { words: ["up", "to"], direction: BOUND_UPPER },
  { words: ["niet", "later", "dan"], direction: BOUND_UPPER }, { words: ["niet", "meer", "dan"], direction: BOUND_UPPER },
  { words: ["uiterlijk"], direction: BOUND_UPPER }, { words: ["maximaal"], direction: BOUND_UPPER }, { words: ["hooguit"], direction: BOUND_UPPER },
  { words: ["ten", "hoogste"], direction: BOUND_UPPER }, { words: ["maximum"], direction: BOUND_UPPER },
  { words: ["no", "earlier", "than"], direction: BOUND_LOWER }, { words: ["not", "earlier", "than"], direction: BOUND_LOWER },
  { words: ["no", "less", "than"], direction: BOUND_LOWER }, { words: ["not", "less", "than"], direction: BOUND_LOWER },
  { words: ["no", "fewer", "than"], direction: BOUND_LOWER }, { words: ["at", "least"], direction: BOUND_LOWER },
  { words: ["niet", "eerder", "dan"], direction: BOUND_LOWER }, { words: ["niet", "minder", "dan"], direction: BOUND_LOWER },
  { words: ["minimaal"], direction: BOUND_LOWER }, { words: ["ten", "minste"], direction: BOUND_LOWER },
  { words: ["tenminste"], direction: BOUND_LOWER }, { words: ["minimum"], direction: BOUND_LOWER },
];

const SPLIT_COMPARATIVES: ReadonlyMap<string, string> = new Map([
  ["meer", BOUND_UPPER], ["more", BOUND_UPPER], ["hoger", BOUND_UPPER], ["higher", BOUND_UPPER],
  ["langer", BOUND_UPPER], ["longer", BOUND_UPPER], ["later", BOUND_UPPER], ["groter", BOUND_UPPER],
  ["larger", BOUND_UPPER], ["bigger", BOUND_UPPER], ["zwaarder", BOUND_UPPER], ["heavier", BOUND_UPPER],
  ["minder", BOUND_LOWER], ["less", BOUND_LOWER], ["fewer", BOUND_LOWER], ["lager", BOUND_LOWER],
  ["lower", BOUND_LOWER], ["korter", BOUND_LOWER], ["shorter", BOUND_LOWER], ["eerder", BOUND_LOWER],
  ["earlier", BOUND_LOWER], ["kleiner", BOUND_LOWER], ["smaller", BOUND_LOWER],
]);

const EXCEED_VERBS: ReadonlySet<string> = new Set(["exceed", "exceeds", "overschrijden", "overschrijdt"]);

export interface SplitBound {
  marker: number;
  direction: string;
}

/** The split bounds in tokens ("mag niet hoger zijn dan", "may not exceed"). */
export function splitBounds(tokens: readonly string[]): SplitBound[] {
  const out: SplitBound[] = [];
  for (let i = 0; i < tokens.length; i++) {
    if (!POLARITY_MARKERS.has(tokens[i] as string)) continue;
    for (let j = i + 1; j < tokens.length && j <= i + 4; j++) {
      if (EXCEED_VERBS.has(tokens[j] as string)) {
        out.push({ marker: i, direction: BOUND_UPPER });
        break;
      }
      const d = SPLIT_COMPARATIVES.get(tokens[j] as string);
      if (d !== undefined && j + 1 < tokens.length && (tokens[j + 1] === "than" || tokens[j + 1] === "dan")) {
        out.push({ marker: i, direction: d });
        break;
      }
    }
  }
  return out;
}

/** The bound directions present in tokens. */
export function boundDirections(tokens: readonly string[]): Set<string> {
  const out = new Set<string>();
  for (const b of BOUND_PHRASES) if (findSpans(tokens, b.words).length > 0) out.add(b.direction);
  for (const b of splitBounds(tokens)) out.add(b.direction);
  return out;
}

/** Positions of bound phrases in the claim whose direction the passage also has. */
function boundMarkerPositions(tokens: readonly string[], passage: ReadonlySet<string>): Set<number> {
  const out = new Set<number>();
  for (const b of BOUND_PHRASES) {
    if (!passage.has(b.direction)) continue;
    for (const sp of findSpans(tokens, b.words)) for (let i = sp.start; i < sp.end; i++) out.add(i);
  }
  for (const b of splitBounds(tokens)) if (passage.has(b.direction)) out.add(b.marker);
  return out;
}

/** A number's key, with an amount in cents read in euros ("23 cent" = 0.23). */
function centsAsEuros(m: NumberMatch): string {
  switch (m.unit) {
    case "cent":
    case "cents":
    case "ct":
    case "eurocent":
    case "eurocents":
      if (m.reading.value !== null) return ratKey(Rat.fromDecimal(m.reading.value).quo(new Rat(100n)));
  }
  return m.reading.key;
}

/** ISO codes a claim writes for the euro sign ("EUR 2.40"). */
const CURRENCY_CODES: ReadonlySet<string> = new Set(["eur", "usd", "gbp"]);

/** Carry a negation in the word itself (passage side only). */
const NEGATIVE_WORDS: ReadonlySet<string> = new Set([
  "unused", "unpaid", "untaken", "unclaimed", "unspent",
  "ongebruikt", "ongebruikte", "onbetaald", "onbetaalde", "onopgenomen",
]);

