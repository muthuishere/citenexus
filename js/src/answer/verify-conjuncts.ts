// The conjunct-token guard: a claim that drops a conjunct of the unit's
// condition which holds a LANGUAGE-FREE token — a number or a proper name —
// port of golang/answer/verify_conjuncts.go. Only language-free tokens decide;
// a conjunct without one gives no verdict. Can only refuse.

import { tokenizeV2 } from "../tokenize/tokenize-v2.js";
import { cmpGo, findFirst, goFields, goLower, goQuote, goSplit, goTrim, goTrimLeft, goTrimSpace, isUpperRune, matches, replaceAll, runes } from "./gotext.js";
import { numbersIn } from "./numbers.js";
import { primaryLanguage } from "./verify-answer.js";
import type { EvidenceUnit } from "./verify-answer.js";
import { Carrier, conditionContent } from "./verify-conditions.js";
import type { GuardConfig } from "./verify-guards.js";
import { numberWordValue, softJoin } from "./verify-guards-model.js";
import { sentenceBreak } from "./verify-parties.js";
import { glossIdx } from "./glossary.js";

// Go's (?i) patterns; ASCII keywords, so JS's `i` (without `u`) folds the same.
const CONJUNCT_OPENER =
  /\b(mits|indien|tenzij|zolang|op voorwaarde dat|alleen als|provided that|provided|unless|only if|as long as)\b/dgi;
const CONJUNCT_SPLIT = /,|\b(?:en|and)\b/dgi;
const CONJUNCT_COORDINATOR = /\b(?:en|and)\b/dgi;
const TOT_EN_MET_WORDS = /\btot en met\b|\bup to and including\b/dgi;

/** The number keys and the proper names of a text. */
export function languageFree(text: string, language: string): Set<string> {
  const out = new Set<string>();
  for (const m of numbersIn(text, language)) out.add("#" + m.reading.key);
  const words = goFields(text);
  for (let i = 0; i < words.length; i++) {
    const w = goTrim(words[i] as string, ".,;:()\"'!?");
    const r = runes(w);
    if (i === 0 || r.length < 3 || !isUpperRune(r[0])) continue;
    const prev = words[i - 1] as string;
    if (prev.endsWith(".") || prev.endsWith(":")) continue; // a sentence start inside the text
    out.add("@" + goLower(w));
  }
  return out;
}

/** The claim holds the token — same number key, the number spelled out, or the same name. */
function claimCarriesToken(tok: string, claimFree: ReadonlySet<string>, claimTokens: readonly string[]): boolean {
  if (claimFree.has(tok)) return true;
  if (tok.startsWith("@")) {
    const name = tok.slice(1);
    return claimTokens.includes(name);
  }
  for (const t of claimTokens) {
    const [v, ok] = numberWordValue(t);
    if (ok && "#" + v === tok) return true;
  }
  return false;
}

/** The conjuncts of a sentence's condition, each with its language-free tokens;
 * null when the sentence has none, or only one. */
function conditionConjuncts(sentence: string, language: string): Set<string>[] | null {
  const loc = findFirst(CONJUNCT_OPENER, sentence);
  if (loc === null) return null;
  const span = replaceAll(TOT_EN_MET_WORDS, sentence.slice(loc.end), "tot_en_met");
  let segs = span.split(",");
  while (segs.length > 1 && !matches(CONJUNCT_COORDINATOR, segs[segs.length - 1] as string)) segs = segs.slice(0, -1);
  const out: Set<string>[] = [];
  let parts = 0;
  for (const p of goSplit(CONJUNCT_SPLIT, segs.join(","))) {
    if (goTrimSpace(p) === "") continue;
    parts++;
    out.push(languageFree(p, language));
  }
  if (parts < 2) return null;
  return out;
}

/** conjunctTokenGuard: see the file comment. */
export function conjunctTokenGuard(claim: string, claimLanguage: string, eu: EvidenceUnit, cfg: GuardConfig): string {
  if (cfg.fragment) return "";
  const sentences = goSplit(sentenceBreak, softJoin(eu.text));
  const claimTokens = tokenizeV2(claim);
  const claimFree = languageFree(claim, claimLanguage);
  let best = -1;
  const frees = sentences.map((s) => languageFree(s, eu.language));
  for (let i = 0; i < sentences.length; i++) {
    const sFree = frees[i] as Set<string>;
    for (const tok of claimFree) {
      if (!sFree.has(tok)) continue;
      let unique = true;
      for (let j = 0; j < sentences.length; j++) {
        if (j !== i && (frees[j] as Set<string>).has(tok)) {
          unique = false;
          break;
        }
      }
      if (unique) {
        if (best >= 0 && best !== i) return ""; // anchored to two sentences: no verdict
        best = i;
      }
    }
  }
  if (best < 0) {
    const cross =
      claimLanguage !== "" && eu.language !== "" && primaryLanguage(claimLanguage) !== primaryLanguage(eu.language);
    const c = new Carrier(new Set(claimTokens), cross, glossIdx(cfg.gloss));
    let bestN = 0;
    let tie = false;
    for (let i = 0; i < sentences.length; i++) {
      let n = 0;
      const seen = new Set<string>();
      for (const t of tokenizeV2(sentences[i] as string)) {
        if (c.carried(t)[0] && conditionContent(t) && !seen.has(t)) {
          seen.add(t);
          n++;
        }
      }
      if (n > bestN) {
        best = i;
        bestN = n;
        tie = false;
      } else if (n === bestN && n > 0) {
        tie = true;
      }
    }
    if (bestN < 2 || tie) return "";
  }
  for (const conj of conditionConjuncts(sentences[best] as string, eu.language) ?? []) {
    if (conj.size === 0) continue; // no language-free token: no verdict on this conjunct
    let missing = "";
    for (const tok of conj) {
      if (claimCarriesToken(tok, claimFree, claimTokens)) {
        missing = "";
        break;
      }
      if (missing === "" || cmpGo(tok, missing) < 0) missing = tok;
    }
    if (missing !== "") {
      return `condition guard: the passage's condition includes ${goQuote(goTrimLeft(missing, "#@"))} and the claim drops that part`;
    }
  }
  return "";
}
