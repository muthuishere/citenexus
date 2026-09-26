// Headings a host must not exempt from verification — port of
// golang/answer/heading.go.
//
// verifyAnswer exempts nothing: a Markdown heading is a claim like any other
// line. Hosts that serve an answer with its layout exempt refused lines that
// make no factual assertion; a host asks two questions before it exempts one:
//
//   const [claim] = headingNeedsCheck(line, lang);
//   if (claim) { /* keep verifyAnswer's verdict */ }
//   else if (headingNameUnsupported(line, evidence, aliases) !== "") { /* refuse */ }
//   else { /* exempt: served unchecked */ }
//
// Both can only turn an exemption into a refusal; neither admits anything.

import { isStopword } from "../gate/gate.js";
import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { GS, containsAny, findAllStrings, goLower, goQuote, goTrim, goTrimSpace, isDigitRune, isLetterRune, isUpperRune, replaceAll, runes } from "./gotext.js";
import { primaryLanguage, stripMarkup } from "./verify-answer.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { CALENDAR_FOLD, absentName, equalTokens, names } from "./verify-guards.js";
import { CONTEXT_STOP, NUMBER_WORDS } from "./verify-guards-model.js";
import { LIST_LEAD_TOKEN } from "./verify-roles.js";

/** The closed word tables headingNeedsCheckWith reads, keyed by primary
 * language subtag. A heading in a language with no entry (or undeclared) is
 * read against every language's table. */
export interface HeadingRules {
  /** obligation / permission words and phrases ("moet", "recht op", "must") */
  modals?: Readonly<Record<string, readonly string[]>>;
  /** words that restrict to one case ("alleen", "only") */
  exclusives?: Readonly<Record<string, readonly string[]>>;
  /** finite verbs; one plus more than verbWords words makes a sentence */
  verbs?: Readonly<Record<string, readonly string[]>>;
  /** the word count a verb-bearing heading must EXCEED; 0 means the default */
  verbWords?: number;
}

/** "Wat je krijgt bij ziekte" (5 words) stays a heading. */
export const DEFAULT_HEADING_VERB_WORDS = 5;

export const DEFAULT_HEADING_RULES: HeadingRules = Object.freeze({
  modals: {
    nl: ["mag", "mogen", "moet", "moeten", "verplicht", "verplichte", "recht op"],
    en: ["must", "may", "shall", "entitled"],
  },
  exclusives: {
    nl: ["alleen", "uitsluitend", "enkel", "slechts"],
    en: ["only", "solely", "exclusively"],
  },
  verbs: {
    nl: ["is", "zijn", "wordt", "worden", "heeft", "hebben", "krijgt", "krijg", "krijgen",
      "geldt", "gelden", "kan", "kun", "kunt", "kunnen", "betaalt", "betalen", "valt", "vallen",
      "blijft", "blijven", "gaat", "gaan", "loopt", "telt", "vervalt", "ontvang", "ontvangt",
      "bouw", "bouwt", "neem", "neemt"],
    en: ["is", "are", "has", "have", "can", "will", "get", "gets", "applies", "apply", "pays",
      "pay", "counts", "remains", "stays", "receive", "receives", "take", "takes", "need",
      "needs", "does", "do"],
  },
  verbWords: 0,
});

/** Whether a line a host would exempt as a heading states a rule: [claim, reason]. */
export function headingNeedsCheck(heading: string, language: string): [boolean, string] {
  return headingNeedsCheckWith(heading, language, DEFAULT_HEADING_RULES);
}

/** headingNeedsCheck with the host's own tables; they replace the defaults
 * entirely. Numbers are always read. */
export function headingNeedsCheckWith(heading: string, language: string, rules: HeadingRules): [boolean, string] {
  const text = headingText(heading);
  const words = findAllStrings(LIST_LEAD_TOKEN, text);
  const tokens = tokenizeV2(text);
  const capitalised = new Set<string>();
  const lowered = new Set<string>();
  for (const w of words) {
    for (const tok of tokenizeV2(w)) {
      const r = runes(goTrim(w, "\"'“”‘’()[]{}.,;:!?"));
      if (r.length > 0 && isUpperRune(r[0])) capitalised.add(tok);
      else lowered.add(tok);
    }
  }
  const lang = primaryLanguage(language);
  let [w, ok] = matchTable(tokens, tableFor(rules.modals, lang), (x) => CALENDAR_FOLD.has(x) && capitalised.has(x) && !lowered.has(x));
  if (ok) return [true, `heading states a rule: modal ${goQuote(w)}`];
  [w, ok] = matchTable(tokens, tableFor(rules.exclusives, lang), null);
  if (ok) return [true, `heading states a rule: exclusive ${goQuote(w)}`];
  for (const tok of tokens) {
    if (containsAny(tok, "0123456789")) return [true, `heading states a rule: number ${goQuote(tok)}`];
    if (NUMBER_WORDS.has(tok) && tok !== "een" && tok !== "one") {
      return [true, `heading states a rule: number ${goQuote(tok)}`];
    }
  }
  let limit = rules.verbWords ?? 0;
  if (limit === 0) limit = DEFAULT_HEADING_VERB_WORDS;
  if (tokens.length > limit) {
    [w, ok] = matchTable(tokens, tableFor(rules.verbs, lang), null);
    if (ok) return [true, `heading states a rule: verb ${goQuote(w)} in ${tokens.length} words`];
  }
  return [false, ""];
}

/**
 * A refusal reason when the heading names something — a name as the name guard
 * reads it — that appears in NONE of the evidence units. "" when every name is
 * somewhere in the evidence. A Title Case heading carries no case signal: only
 * acronyms and letter+digit words count there.
 */
export function headingNameUnsupported(
  heading: string,
  evidence: readonly EvidenceUnit[],
  aliases: Readonly<Record<string, readonly string[]>> | null | undefined,
): string {
  const text = headingText(heading);
  let found = names(text);
  if (titleCase(text)) found = found.filter(strong);
  if (found.length === 0) return "";
  let all = "";
  for (const eu of evidence) all += eu.text + "\n" + eu.documentId + "\n";
  const name = absentName(found, all, aliases);
  if (name !== "") return `heading name guard: ${goQuote(name)} is in no evidence unit`;
  return "";
}

const HEADING_MARKER = new RegExp(`^[${GS}]*(?:#{1,6}[${GS}]+|>[${GS}]*|(?:[-*•·]|[0-9]{1,3}[.)])[${GS}]+)*`, "dgu");

/** The heading as a reader sees it: markup and a leading marker removed. */
function headingText(heading: string): string {
  return goTrimSpace(replaceAll(HEADING_MARKER, stripMarkup(heading), ""));
}

function tableFor(table: Readonly<Record<string, readonly string[]>> | undefined, lang: string): readonly string[] {
  if (table === undefined) return [];
  if (Object.hasOwn(table, lang)) return table[lang] as readonly string[];
  const all: string[] = [];
  for (const entries of Object.values(table)) all.push(...entries);
  return all;
}

/** The first entry (a word or a phrase) found in tokens. */
function matchTable(
  tokens: readonly string[],
  entries: readonly string[],
  skip: ((w: string) => boolean) | null,
): [string, boolean] {
  for (const entry of entries) {
    const et = tokenizeV2(entry);
    if (et.length === 0) continue;
    for (let i = 0; i + et.length <= tokens.length; i++) {
      if (!equalTokens(tokens.slice(i, i + et.length), et)) continue;
      if (et.length === 1 && skip !== null && skip(et[0] as string)) continue;
      return [entry, true];
    }
  }
  return ["", false];
}

/** At least two words, and every non-function word starts with a capital. */
function titleCase(text: string): boolean {
  let capitals = 0;
  for (const w of findAllStrings(LIST_LEAD_TOKEN, text)) {
    const bare = goTrim(w, "\"'“”‘’()[]{}.,;:!?|");
    const r = runes(bare);
    if (r.length === 0 || !isLetterRune(r[0])) continue;
    if (isUpperRune(r[0])) {
      capitals++;
      continue;
    }
    const low = goLower(bare);
    if (CONTEXT_STOP.has(low) || isStopword(low)) continue;
    return false;
  }
  return capitals >= 2;
}

/** A name by its form, not its case — an acronym or letters with digits. */
function strong(name: string): boolean {
  let hasDigit = false;
  let hasLetter = false;
  let allUpper = true;
  for (const r of name) {
    if (isDigitRune(r)) hasDigit = true;
    else if (isLetterRune(r)) {
      hasLetter = true;
      if (!isUpperRune(r)) allUpper = false;
    }
  }
  return hasLetter && (hasDigit || allUpper);
}
