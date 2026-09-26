// VerifyOptions.conjunctPresence: the cross-language condition reading, off by
// default — port of golang/answer/verify_conjunct_presence.go.
//
//   - NO-VERDICT BRANCH: for a cross-language claim that states a condition of
//     its own, a glossary can SATISFY a condition word but never show it missing.
//   - PER-CONJUNCT PRESENCE: that branch must not pass a partial condition —
//     when the claim's own condition has fewer parts than the unit's, every
//     conjunct must be positively present.

import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { findFirst, goLower, goSplit, isLetterRune, replaceAll } from "./gotext.js";
import { primaryLanguage } from "./verify-answer.js";
import { conditionContent } from "./verify-conditions.js";
import type { Carrier } from "./verify-conditions.js";

export const crossConditionMarkers: readonly (readonly string[])[] = [
  ["if"], ["when"], ["whenever"], ["once"], ["provided"], ["unless"], ["as", "long", "as"], ["who"],
  ["whose"], ["which"], ["that"], ["with"], ["without"], ["after"], ["before"], ["on"], ["only"],
  ["except"], ["subject", "to"], ["where"], ["in", "case"],
  ["als"], ["wanneer"], ["indien"], ["mits"], ["zodra"], ["zolang"], ["tenzij"], ["die"], ["dat"],
  ["met"], ["zonder"], ["na"], ["op"], ["alleen"], ["behalve"], ["bij"],
];

// Go's (?i) patterns over ASCII keywords.
const PRESENCE_OPENER =
  /\b(mits|indien|tenzij|zolang|wanneer|als|die|op voorwaarde dat|provided that|provided|unless|if|when|once|who)\b/dgi;
const PRESENCE_SPLIT = /,|\b(?:zowel|both|as well as)\b|\b(?:en|and)\b/dgi;
const PRESENCE_COORDINATOR = /\b(?:en|and|zowel|both|as well as)\b/dgi;
const PRESENCE_TOT_EN_MET = /\btot en met\b/dgi;

const PRESENCE_FUNCTION_WORDS: ReadonlySet<string> = new Set([
  "they", "them", "their", "have", "been", "would", "could",
  "should", "hebben", "heeft", "zich", "deze", "werd",
  "werden", "zullen", "zouden",
]);

function testRe(re: RegExp, s: string): boolean {
  re.lastIndex = 0;
  const ok = re.test(s);
  re.lastIndex = 0;
  return ok;
}

/**
 * The unit sentence's conjunctive condition against the claim: a word of a
 * conjunct the claim does not positively carry and the conjunct count, when the
 * claim's own condition has fewer conjuncts than the unit's; else ["", 0].
 */
export function droppedConjunct(claim: string, sentence: string, sentenceLanguage: string, c: Carrier): [string, number] {
  const loc = findFirst(PRESENCE_OPENER, sentence);
  if (loc === null) return ["", 0];
  if (goLower(sentence.slice(loc.start, loc.end)) === "als" && goLower(sentence.slice(0, loc.start)).includes("zowel")) {
    return ["", 0];
  }
  const before = new Set(tokenizeV2(sentence.slice(0, loc.start)));
  const span = replaceAll(PRESENCE_TOT_EN_MET, sentence.slice(loc.end), "tot_en_met");
  let segs = span.split(",");
  while (segs.length > 1 && !testRe(PRESENCE_COORDINATOR, segs[segs.length - 1] as string)) segs = segs.slice(0, -1);
  const conjuncts: string[][] = [];
  for (const p of goSplit(PRESENCE_SPLIT, segs.join(","))) {
    const ws = tokenizeV2(p).filter((t) => conditionContent(t) && !PRESENCE_FUNCTION_WORDS.has(t) && !before.has(t));
    if (ws.length > 0) conjuncts.push(ws);
  }
  const n = conjuncts.length;
  if (n < 2) return ["", 0];
  if (primaryLanguage(sentenceLanguage) === "nl") {
    const last = conjuncts[n - 1] as string[];
    if (last.length >= 2 && isWord(last[last.length - 1] as string)) conjuncts[n - 1] = last.slice(0, -1);
  }
  let absent = "";
  for (const ws of conjuncts) {
    const present = ws.some((w) => c.carried(w)[0]);
    if (!present && absent === "") absent = ws[0] as string;
  }
  if (absent === "") return ["", 0];
  const lc = goLower(claim);
  let cl: [number, number] | null = null;
  const m = findFirst(PRESENCE_OPENER, lc);
  if (m !== null) cl = [m.start, m.end];
  if (cl === null) {
    for (const mk of [" with ", " met ", " after ", " na ", " on ", " op "]) {
      const i = lc.indexOf(mk);
      if (i >= 0) {
        cl = [i, i + mk.length];
        break;
      }
    }
  }
  if (cl === null) return ["", 0];
  const parts = goSplit(PRESENCE_SPLIT, replaceAll(PRESENCE_TOT_EN_MET, lc.slice(cl[1]), "tot_en_met")).length;
  if (parts >= n) return ["", 0]; // as many conditions as the unit: may be all of them, in other words
  return [absent, n];
}

function isWord(t: string): boolean {
  if (t === "") return false;
  for (const r of t) if (!isLetterRune(r)) return false;
  return true;
}
