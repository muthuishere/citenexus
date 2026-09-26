// verifyAnswer — cite-or-abstain for an answer the CALLER already generated.
// A byte-for-byte behavioural port of golang/answer/verify_answer.go (ADR-0016),
// pinned by conformance/cases/verify_answer.json.
//
// askWith owns the whole flow: it retrieves, generates from ONE passage and gates
// every claim against that passage. verifyAnswer is the retrieval-free half: it
// takes the answer and the evidence the writer saw, and returns the same Result
// shape — only verified claims survive, every claim keeps its verdict, and an
// answer with nothing verified abstains.
//
// ## The citation contract
//
// The writer ends each claim with the evidence-unit ids it rests on:
//
//     De vergoeding is € 25 inclusief btw [eu:hr-12#3]. Aanvragen gaan via HR [eu:hr-12#4, eu:hr-09#1].
//
// `[eu:a][eu:b]`, `[eu:a, b]` and `[eu:a, eu:b]` are all accepted. Markers are
// removed from the claim text before it is checked, and never appear in
// Result.answer. `[q:<facet-id>]` tags the part of the question a claim answers.
//
// ## What admits a claim, in order
//
//  1. GATE — the ADR-0009 predicate (isSupportedV2) against a cited unit, or,
//     uncited and citations not required, any selected unit, most authoritative
//     first. verified_by "gate".
//  2. QUOTE — a verbatim quote (≥ MIN_QUOTE_TOKENS tokens) that passes the gate
//     against a cited unit, AND the checker entails the whole claim from it.
//     verified_by "quote+model:<name>".
//  3. MODEL — the checker entails the claim from a cited unit in another
//     declared language (or any, under admitParaphrase). verified_by "model:<name>".
//  4. UNION — a list item joined to a content lead-in citing different units
//     (verify-union.ts).
//
// Steps 2–4 need an injected SupportChecker, and every admission they make must
// also pass the deterministic guards, which the model cannot override. And what
// removes one again — every rule can only ADD abstention: a checker
// contradiction (veto); a conflict with a MORE authoritative unit; a conflict
// with an EQUALLY authoritative unit (unresolved — both sides reported).
//
// FAILURE IS AN ERROR, NOT A REFUSAL: invalid evidence or a checker failure
// rejects; a refusal is only ever a finding about the evidence.

import { isStopword } from "../gate/gate.js";
import { isSupportedV2, POLARITY_MARKERS } from "../gate/verify-v2.js";
import { AUTO_ANSWER_LANGUAGE, resolveAnswerLanguage } from "../lang/lang.js";
import type { Claim, EvidenceSignals, Result, SourceRef } from "../result/result.js";
import { Decision, TrustMode, sourceRef } from "../result/result.js";
import { tokenizeV2, unsupportedScripts } from "../tokenize/tokenize-v2.js";
import type { SupportChecker, SupportScores } from "../contracts.js";
import { AuthorityPolicy, INSUFFICIENT_AUTHORITY, selectByAuthority, tierOutranks } from "../authority/authority.js";
import type { AuthorityTier } from "../authority/authority.js";
import { CONFLICT_REFUSAL_ANSWER, REFUSAL_ANSWER } from "./answer.js";
import { collapseNearDuplicates, detectConflict } from "./conflict.js";
import type { ConflictFinding } from "./conflict.js";
import { splitClaims } from "./segment.js";
import {
  GS,
  cmpGo,
  findAll,
  findAllStrings,
  fmt3,
  goLower,
  goQuote,
  goTrim,
  goTrimSpace,
  isLetterRune,
  isUpperRune,
  matches,
  replaceAll,
  runes,
} from "./gotext.js";
import { numbersIn } from "./numbers.js";
import {
  clauseNegationGuard,
  guards,
  numberGuard,
  quotes,
  truncationGuard,
} from "./verify-guards.js";
import type { GuardConfig } from "./verify-guards.js";
import { unitOf } from "./verify-guards-model.js";
import { DEFAULT_ACTOR_LEXICON, LIST_LEAD_TOKEN, roleGuard } from "./verify-roles.js";
import type { ActorLexicon } from "./verify-roles.js";
import { relationGuard } from "./verify-relations.js";
import { exclusionGuard } from "./verify-exclusions.js";
import { definitionGuard, documentDefinitions } from "./verify-definitions.js";
import { DEFAULT_SUBTYPE_HEADS, subtypeGuard } from "./verify-subtypes.js";
import type { SubtypeHead } from "./verify-subtypes.js";
import { conditionGuard } from "./verify-conditions.js";
import { conjunctTokenGuard } from "./verify-conjuncts.js";
import { hedgeGuard } from "./verify-hedges.js";
import { pairValueGuard } from "./verify-parties.js";
import { DEFAULT_QUALIFIER_PAIRS } from "./verify-qualifier-pairs.js";
import type { QualifierPair } from "./verify-qualifier-pairs.js";
import { DEFAULT_VERB_PAIRS } from "./verify-verbpairs.js";
import type { VerbPair } from "./verify-verbpairs.js";
import { preparedFor } from "./glossary.js";
import type { GlossaryEntry, PreparedGlossary } from "./glossary.js";
import { unionPremise, unionRefusal } from "./verify-union.js";

/** One citable passage the writer saw. */
export interface EvidenceUnit {
  /** what the writer cites in `[eu:<id>]`; required, unique */
  id: string;
  documentId: string;
  text: string;
  /** the DECLARED language ("nl", "en", "nl-NL"); never detected. "" disables
   * model admission for this unit. */
  language: string;
  /** caller metadata read ONLY by VerifyOptions.authority (ADR-0004) */
  authority?: Readonly<Record<string, string>>;
}

/** One part of the question an answer must cover. */
export interface Facet {
  /** what the writer cites in `[q:<id>]` */
  id: string;
  /** what missing_evidence names; the id when empty */
  label?: string;
}

/** verifyAnswer's options. The empty object is deterministic-only, unranked,
 * citations optional. */
export interface VerifyOptions {
  /** the language the answer was written in; model admission requires it */
  answerLanguage?: string;
  /** ranks units and, with a floor, excludes them; default ranks all equal */
  authority?: AuthorityPolicy;
  /** drop every claim that carries no `[eu:...]` marker */
  requireCitations?: boolean;
  /** the optional injected support checker */
  checker?: SupportChecker | null;
  /** labels model-admitted claims: verified_by = "model:" + checkerName */
  checkerName?: string;
  /** caller-owned, closed name aliases keyed by ONE lowercase name word */
  nameAliases?: Readonly<Record<string, readonly string[]>> | null;
  /** content-free list lead-ins; undefined means DEFAULT_LEAD_IN_FRAMES, [] none */
  leadInFrames?: readonly string[] | null;
  /** the role guard's lexicon; undefined means DEFAULT_ACTOR_LEXICON */
  actors?: ActorLexicon | null;
  /** undefined means DEFAULT_QUALIFIER_PAIRS; [] turns the comparison off */
  qualifierPairs?: readonly QualifierPair[] | null;
  /** undefined means DEFAULT_VERB_PAIRS; [] turns the guard off */
  verbPairs?: readonly VerbPair[] | null;
  /** turns off the definition guard */
  disableDefinitions?: boolean;
  /** undefined means DEFAULT_SUBTYPE_HEADS; [] turns the guard off */
  subtypeHeads?: readonly SubtypeHead[] | null;
  /** the caller's term pairs across languages, lowercase, either order */
  glossary?: readonly (readonly [string, string])[] | null;
  /** glossary rows with lemmas, a separable particle and a class */
  glossaryEntries?: readonly GlossaryEntry[] | null;
  /** glossary + glossaryEntries indexed once by prepareGlossary */
  glossaryPrepared?: PreparedGlossary | null;
  /** let the checker admit SAME-language claims the gate rejected */
  admitParaphrase?: boolean;
  /** the parts of the question the answer must cover */
  facets?: readonly Facet[] | null;
  /** minimum entailment for a model or quote admission; 0 means the default */
  entailThreshold?: number;
  /** contradiction score at which the checker vetoes; 0 means the default */
  contradictThreshold?: number;
  /** the cross-language condition reading of verify-conjunct-presence.ts */
  conjunctPresence?: boolean;
}

/** Deliberately conservative: a wrongly admitted claim costs more than a
 * wrongly dropped one. */
export const DEFAULT_ENTAIL_THRESHOLD = 0.9;
export const DEFAULT_CONTRADICT_THRESHOLD = 0.5;

// Claim.reason values for a dropped claim.
export const REASON_UNCITED = "uncited";
export const REASON_UNKNOWN_CITATION = "cites unknown evidence unit";
export const REASON_BELOW_FLOOR = "cited evidence is below the authority floor";
export const REASON_NOT_SUPPORTED = "not supported by the cited evidence";
export const REASON_CONTRADICTED = "contradicted by the cited evidence";
export const REASON_OUTRANKED = "contradicted by a more authoritative source";
export const REASON_UNRESOLVED_CLAIMS = "cited sources disagree and the conflict is unresolved";

/** Every evidence-validation error. */
export class InvalidEvidenceError extends Error {
  constructor(detail: string) {
    super(`answer: invalid evidence: ${detail}`);
    this.name = "InvalidEvidenceError";
  }
}

/** The answer language when nothing declares one (golang defaultAnswerLanguage). */
const DEFAULT_ANSWER_LANGUAGE = "en";
/** What a SourceRef reports when the cited document declared no language. */
const UNDECLARED_LANGUAGE = "und";

/** One `[eu:...]` or `[q:...]` group; the body is a comma list. */
const CITATION_MARKER = new RegExp(`[${GS}]*\\[[${GS}]*(eu|q)[${GS}]*:([^\\]]*)\\]`, "dgu");

export interface CitedClaim {
  text: string;
  cited: string[];
  facets: string[];
  // A list item joined to a content lead-in keeps its parts: lead is the lead-in
  // as joined (qualifiers stripped), item the item alone, and leadCited /
  // itemCited the units each part cited itself. Empty otherwise.
  lead: string;
  item: string;
  leadCited: string[];
  itemCited: string[];
}

function newClaim(text: string): CitedClaim {
  return { text, cited: [], facets: [], lead: "", item: "", leadCited: [], itemCited: [] };
}

/** Split the answer into claims and attach each marker to the claim it follows. */
export function parseCitations(answer: string): CitedClaim[] {
  return parseCitationsWith(answer, DEFAULT_LEAD_IN_FRAMES);
}

export function parseCitationsWith(answer: string, frames: readonly string[]): CitedClaim[] {
  let clean = "";
  const marks: { at: number; facet: boolean; ids: string[] }[] = [];
  let last = 0;
  for (const m of findAll(CITATION_MARKER, answer)) {
    clean += answer.slice(last, m.start);
    const kind = m.group(1) as string;
    const ids: string[] = [];
    for (const part of (m.group(2) as string).split(",")) {
      let id = goTrimSpace(part);
      if (id.startsWith(kind + ":")) id = id.slice(kind.length + 1);
      id = goTrimSpace(id);
      if (id !== "") ids.push(id);
    }
    marks.push({ at: clean.length, facet: kind === "q", ids });
    last = m.end;
  }
  clean += answer.slice(last);
  const text = clean;

  const texts = splitClaims(text);
  const claims = texts.map(newClaim);
  const starts: number[] = [];
  let cursor = 0;
  for (const t of texts) {
    const at = text.indexOf(t, cursor);
    if (at >= 0) cursor = at;
    starts.push(cursor);
    cursor += t.length;
  }
  for (const m of marks) {
    let owner = 0;
    starts.forEach((s, i) => {
      if (s <= m.at) owner = i;
    });
    if (claims.length === 0) continue;
    const c = claims[owner] as CitedClaim;
    if (m.facet) c.facets = appendUnique(c.facets, ...m.ids);
    else c.cited = appendUnique(c.cited, ...m.ids);
  }
  return joinListItems(claims, frames);
}

const BARE_LIST_MARKER = /^([-*•·]|[0-9]{1,3}[.)]|[a-z][.)])$/dgu;
const LIST_ITEM_PREFIX = new RegExp(`^([-*•·]|[0-9]{1,3}[.)]|[a-z][.)])[${GS}]+`, "dgu");

/** Make list items standalone claims (see golang joinListItems). */
function joinListItems(claims: CitedClaim[], frames: readonly string[]): CitedClaim[] {
  const merged: CitedClaim[] = [];
  for (let i = 0; i < claims.length; i++) {
    const c = claims[i] as CitedClaim;
    if (matches(BARE_LIST_MARKER, goTrimSpace(c.text)) && i + 1 < claims.length) {
      const next = { ...(claims[i + 1] as CitedClaim) };
      next.text = goTrimSpace(c.text) + " " + next.text;
      next.cited = appendUnique([...c.cited], ...next.cited);
      next.facets = appendUnique([...c.facets], ...next.facets);
      claims[i + 1] = next;
      continue;
    }
    merged.push(c);
  }

  const out: CitedClaim[] = [];
  let leadIn: CitedClaim | null = null;
  let joinText = "";
  let ownClaim = -1; // index in out of a verified exclusive/counted lead-in
  for (let i = 0; i < merged.length; i++) {
    const c = { ...(merged[i] as CitedClaim) };
    const loc = findAll(LIST_ITEM_PREFIX, c.text)[0];
    if (loc === undefined) {
      leadIn = null;
      ownClaim = -1;
      if (
        goTrimSpace(c.text).endsWith(":") &&
        i + 1 < merged.length &&
        matches(LIST_ITEM_PREFIX, (merged[i + 1] as CitedClaim).text)
      ) {
        // golang copies the struct (`lead := c`): the lead-in's citations are a
        // value, never the array the exclusive lead-in's own claim grows below.
        leadIn = { ...c, cited: [...c.cited], facets: [...c.facets] };
        const bare = goTrimSpace(c.text).slice(0, -1);
        const [stripped, marked] = stripListQualifiers(bare);
        joinText = stripped;
        if (!marked && contentFreeLeadIn(bare, frames)) {
          leadIn = { ...newClaim(""), cited: [...c.cited], facets: [...c.facets] };
          joinText = "";
          continue;
        }
        if (marked) {
          ownClaim = out.length;
          out.push(c);
        }
        continue; // otherwise structural: carried into its items only
      }
      out.push(c);
      continue;
    }
    const item = goTrimSpace(c.text.slice(loc.end));
    if (leadIn === null) {
      c.text = item;
      out.push(c);
      continue;
    }
    if (joinText === "") {
      c.text = item;
    } else {
      c.text = joinText + " " + lowerFirst(item);
      c.lead = joinText;
      c.item = lowerFirst(item);
      c.leadCited = leadIn.cited;
      c.itemCited = c.cited;
    }
    c.cited = appendUnique([...c.cited], ...leadIn.cited);
    c.facets = appendUnique([...c.facets], ...leadIn.facets);
    if (ownClaim >= 0) {
      const own = out[ownClaim] as CitedClaim;
      own.cited = appendUnique(own.cited, ...c.cited);
      own.facets = appendUnique(own.facets, ...c.facets);
    }
    out.push(c);
  }
  return out;
}

/** A small, generic nl/en table of content-free list lead-ins. */
export const DEFAULT_LEAD_IN_FRAMES: readonly string[] = Object.freeze([
  "zo zit het", "zo werkt het", "het volgende", "als volgt", "hieronder",
  "samengevat", "kort samengevat", "in het kort", "een overzicht",
  "here's how", "here is how", "here's what", "here is what", "as follows",
  "the following", "below", "in short", "in summary", "an overview",
  "volg deze stappen", "volg de stappen", "volg de volgende stappen",
  "de volgende stappen", "deze stappen", "de stappen", "stappen",
  "hier zijn de stappen", "hier zijn de exacte stappen",
  "here are the steps", "here are the exact steps", "follow these steps",
  "follow the steps", "these steps", "the steps", "steps",
]);

/** Every token of the lead-in is covered by a frame or is a non-polarity
 * stopword, and at least one frame matched. */
function contentFreeLeadIn(lead: string, frames: readonly string[]): boolean {
  const toks = tokenizeV2(lead);
  if (toks.length === 0) return false;
  const covered: boolean[] = new Array<boolean>(toks.length).fill(false);
  let matched = false;
  for (const f of frames) {
    const ft = tokenizeV2(f);
    if (ft.length === 0) continue;
    for (let i = 0; i + ft.length <= toks.length; i++) {
      let same = true;
      for (let k = 0; k < ft.length; k++) {
        if (toks[i + k] !== ft[k]) {
          same = false;
          break;
        }
      }
      if (same) {
        matched = true;
        for (let k = 0; k < ft.length; k++) covered[i + k] = true;
      }
    }
  }
  if (!matched) return false;
  for (let i = 0; i < toks.length; i++) {
    if (covered[i]) continue;
    const t = toks[i] as string;
    if (POLARITY_MARKERS.has(t) || !isStopword(t)) return false;
  }
  return true;
}

const LIST_EXCLUSIVES: ReadonlySet<string> = new Set([
  "alleen", "uitsluitend", "enkel", "slechts", "only", "solely", "exclusively",
]);

/** Precede a number that names a provision, not a count: "volgens artikel 7 geldt:". */
export const LIST_REFERENCE_NOUNS: ReadonlySet<string> = new Set([
  "artikel", "art", "lid", "hoofdstuk", "paragraaf", "bijlage",
  "article", "section", "chapter", "paragraph", "annex", "clause",
]);

/** Remove a lead-in's exclusivity words and item count; [text, removedAny]. */
function stripListQualifiers(lead: string): [string, boolean] {
  const words = findAllStrings(LIST_LEAD_TOKEN, lead);
  const kept: string[] = [];
  let marked = false;
  words.forEach((w, i) => {
    const bare = goLower(goTrim(w, ",;()\"'"));
    if (LIST_EXCLUSIVES.has(bare)) {
      marked = true;
      return;
    }
    if (isListCount(bare, words, i)) {
      marked = true;
      return;
    }
    kept.push(w);
  });
  return [kept.join(" "), marked];
}

const LIST_COUNT_NUMBER_WORDS: ReadonlyMap<string, string> = new Map([
  ["two", "2"], ["three", "3"], ["four", "4"], ["five", "5"], ["six", "6"], ["seven", "7"],
  ["eight", "8"], ["nine", "9"], ["ten", "10"], ["eleven", "11"], ["twelve", "12"],
  ["twee", "2"], ["drie", "3"], ["vier", "4"], ["vijf", "5"], ["zes", "6"], ["zeven", "7"],
  ["acht", "8"], ["negen", "9"], ["tien", "10"], ["elf", "11"], ["twaalf", "12"],
]);

function isListCount(bare: string, words: readonly string[], i: number): boolean {
  // golang reads numberWords; only its 2–12 entries can pass the switch below.
  let value = LIST_COUNT_NUMBER_WORDS.get(bare);
  if (value === undefined && bare !== "" && bare.charCodeAt(0) >= 48 && bare.charCodeAt(0) <= 57) value = bare;
  if (value === undefined) return false;
  if (!["2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"].includes(value)) return false;
  if (i > 0 && LIST_REFERENCE_NOUNS.has(goLower(goTrim(words[i - 1] as string, ".,;()")))) return false;
  if (i + 1 < words.length && unitOf(goLower(goTrim(words[i + 1] as string, ".,;()")))[2]) return false;
  return true;
}

/** Lowercase an item's first letter when joined mid-sentence — unless it is an
 * acronym or code ("CAO", "WW-uitkering"). */
function lowerFirst(item: string): string {
  const rs = runes(item);
  if (rs.length < 2 || !isUpperRune(rs[0]) || isUpperRune(rs[1]) || !isLetterRune(rs[1])) return item;
  rs[0] = goLower(rs[0] as string);
  return rs.join("");
}

/** An inline link or image: [text](url) / ![alt](url "title"). */
const MD_LINK = new RegExp(
  `!?\\[([^\\[\\]]*)\\]\\([^()${GS}]*(?:\\([^()${GS}]*\\)[^()${GS}]*)*(?:[${GS}]+"[^"]*")?\\)`,
  "dgu",
);
/** Single-character emphasis opened at a word boundary and closed before one. */
const MD_EMPHASIS = new RegExp(
  `(^|[${GS}(\\[{"'“‘])[*_]([^${GS}*_](?:[^*_\\n]*[^${GS}*_])?)[*_]($|[${GS})\\]}"'”’.,;:!?])`,
  "dgu",
);
const MD_STRONG = /\*\*|__|`/g;

/** Markdown emphasis, code backticks and link markup removed, every word kept. */
export function stripMarkup(text: string): string {
  let out = replaceAll(MD_LINK, text, "$1").replace(MD_STRONG, "");
  for (let i = 0; i < 4; i++) {
    const next = replaceAll(MD_EMPHASIS, out, "$1$2$3");
    if (next === out) break;
    out = next;
  }
  return out;
}

function appendUnique(list: string[], ...items: string[]): string[] {
  for (const item of items) if (!list.includes(item)) list.push(item);
  return list;
}

/** The lowercase primary subtag: "nl-NL" -> "nl". */
export function primaryLanguage(code: string): string {
  code = goLower(goTrimSpace(code));
  const i = code.search(/[-_]/);
  return i >= 0 ? code.slice(0, i) : code;
}

interface Verdict {
  facets: string[];
  text: string;
  supported: boolean;
  sources: string[];
  verifiedBy: string;
  reason: string;
}

/**
 * Gate a caller-generated answer against the evidence it cites.
 *
 * FAILURE IS AN ERROR, NOT A REFUSAL: invalid evidence rejects with an
 * InvalidEvidenceError and a checker failure rejects with the checker's error
 * as `cause`; a refusal is only ever a finding about the evidence.
 */
export function verifyAnswer(answer: string, evidence: readonly EvidenceUnit[], options: VerifyOptions = {}): Promise<Result> {
  return verifyAnswerInternal(answer, evidence, options, false);
}

/**
 * verifyAnswer with golang's unexported eagerScoring switch: eager scores every
 * unit the model path reaches whatever the guards decide; the default (lazy)
 * scores a guard-refused unit only when its score can reach the output. The
 * Result is the same either way — tests compare the two.
 */
export async function verifyAnswerInternal(
  answer: string,
  evidence: readonly EvidenceUnit[],
  opts: VerifyOptions,
  eagerScoring: boolean,
): Promise<Result> {
  const byID = new Map<string, number>();
  evidence.forEach((eu, i) => {
    if (eu.id === "") throw new InvalidEvidenceError(`unit ${i} has an empty ID`);
    if (byID.has(eu.id)) throw new InvalidEvidenceError(`duplicate ID ${goQuote(eu.id)}`);
    byID.set(eu.id, i);
  });
  const unitAt = (id: string): EvidenceUnit => evidence[byID.get(id) as number] as EvidenceUnit;
  const entailAt = opts.entailThreshold || DEFAULT_ENTAIL_THRESHOLD;
  const contradictAt = opts.contradictThreshold || DEFAULT_CONTRADICT_THRESHOLD;
  const checker = opts.checker ?? null;
  const modelLabel = opts.checkerName ? "model:" + opts.checkerName : "model";
  const answerLanguageOpt = opts.answerLanguage ?? "";
  const policy = opts.authority ?? new AuthorityPolicy();

  // Observed languages and unreadable scripts, reported, never inputs.
  const languages: string[] = [];
  const seenLanguage = new Set<string>();
  const scripts = new Set<string>(unsupportedScripts(answer));
  for (const eu of evidence) {
    if (eu.language !== "" && !seenLanguage.has(eu.language)) {
      seenLanguage.add(eu.language);
      languages.push(eu.language);
    }
    for (const s of unsupportedScripts(eu.text)) scripts.add(s);
  }
  const unsupported = [...scripts].sort(cmpGo);
  const answerLanguage = resolveAnswerLanguage({
    detection: null,
    answer_language: answerLanguageOpt,
    conversation_language: null,
    languages_in_evidence: languages,
    default_answer_language: DEFAULT_ANSWER_LANGUAGE,
  });
  // "auto" is the detect-it sentinel, not a language.
  let declared = answerLanguageOpt;
  if (goLower(goTrimSpace(declared)) === AUTO_ANSWER_LANGUAGE) declared = "";
  const claimLanguage = primaryLanguage(declared);

  // Authority: it only ever narrows what may be cited.
  const selection = selectByAuthority(evidence, (eu) => eu.authority, policy);
  const selected = selection.candidates;
  const excluded = new Set(selection.excluded.map((eu) => eu.id));
  const tierOf = (eu: EvidenceUnit): AuthorityTier => policy.tierOf(eu.authority);

  // Checker scores, cached per (claim, unit): the veto and the admission ask the same question.
  const cache = new Map<string, SupportScores>();
  const check = async (claim: string, eu: EvidenceUnit): Promise<SupportScores> => {
    const k = `${claim}\u0000${eu.id}`;
    const hit = cache.get(k);
    if (hit !== undefined) return hit;
    let s: SupportScores;
    try {
      s = await (checker as SupportChecker).check(claim, eu.text);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new Error(`answer: support checker on ${goQuote(eu.id)}: ${msg}`, { cause: err });
    }
    const scores = { entailed: s.entailed, contradicted: s.contradicted };
    cache.set(k, scores);
    return scores;
  };

  const actors = opts.actors ?? DEFAULT_ACTOR_LEXICON;
  const cfg: GuardConfig = {
    aliases: opts.nameAliases,
    actors,
    pairs: opts.qualifierPairs ?? DEFAULT_QUALIFIER_PAIRS,
    verbs: opts.verbPairs ?? DEFAULT_VERB_PAIRS,
    gloss: preparedFor(opts),
    noDefinitions: opts.disableDefinitions ?? false,
    docDefs: documentDefinitions(evidence),
    subtypes: opts.subtypeHeads ?? DEFAULT_SUBTYPE_HEADS,
    fragment: false,
    conjunctPresence: opts.conjunctPresence ?? false,
  };
  const frames = opts.leadInFrames ?? DEFAULT_LEAD_IN_FRAMES;
  const parsed = parseCitationsWith(answer, frames);
  const verdicts: Verdict[] = [];
  for (const pc of parsed) {
    // Reported as written; checked with its markup removed.
    const v: Verdict = { text: pc.text, facets: pc.facets, supported: false, sources: [], verifiedBy: "", reason: "" };
    const text = stripMarkup(pc.text);

    // The units this claim may be checked against.
    let candidates: EvidenceUnit[] = [];
    if (pc.cited.length > 0) {
      let unknown = false;
      let belowFloor = false;
      for (const id of pc.cited) {
        const i = byID.get(id);
        if (i === undefined) {
          unknown = true;
          continue;
        }
        if (excluded.has(id)) {
          belowFloor = true;
          continue;
        }
        candidates.push(evidence[i] as EvidenceUnit);
      }
      if (candidates.length === 0) {
        v.reason = REASON_UNKNOWN_CITATION;
        if (belowFloor) v.reason = REASON_BELOW_FLOOR;
        else if (!unknown) v.reason = REASON_NOT_SUPPORTED;
      }
    } else if (opts.requireCitations === true) {
      v.reason = REASON_UNCITED;
    } else {
      candidates = selected;
    }

    // 1. The deterministic gate.
    let gateReason = "";
    let reasonUnits: EvidenceUnit[] = candidates; // whose outcomes decide the refusal reason (F0)
    let guardOf = new Map<string, string>();
    let scoredOf = new Map<string, SupportScores>();
    let scoredOrder: string[] = [];
    const considered = new Set<string>();
    const deferred = new Map<string, EvidenceUnit>();
    for (const eu of candidates) {
      if (!isSupportedV2(text, eu.text)) continue;
      // The gate aligns tokens, and the tokenizer splits "0,23" into 0 and 23:
      // "€ 23" aligns inside "€ 0,23". Numbers are compared as values.
      let reason = numberGuard(text, declared, eu.text, eu.language);
      if (reason === "") reason = clauseNegationGuard(text, eu.text);
      if (reason === "") reason = truncationGuard(text, eu.text);
      if (reason === "" && pc.item !== "") reason = truncationGuard(stripMarkup(pc.item), eu.text);
      if (reason === "") reason = exclusionGuard(text, declared, eu, cfg);
      if (reason === "") reason = definitionGuard(text, declared, eu, cfg);
      if (reason === "") reason = subtypeGuard(text, eu, cfg);
      if (reason === "") reason = conditionGuard(text, declared, eu, cfg);
      if (reason === "") reason = conjunctTokenGuard(text, declared, eu, cfg);
      if (reason === "") reason = hedgeGuard(text, declared, eu, cfg);
      if (reason === "") reason = roleGuard(text, declared, eu, actors);
      if (reason === "") reason = relationGuard(text, declared, eu, actors);
      if (reason === "") reason = pairValueGuard(text, declared, eu);
      if (reason !== "") {
        if (gateReason === "") gateReason = reason; // the FIRST cited unit refused
        if (!guardOf.has(eu.id)) guardOf.set(eu.id, reason);
        continue;
      }
      v.sources.push(eu.id);
      if (pc.cited.length === 0) break;
    }
    if (v.sources.length > 0) {
      v.supported = true;
      v.verifiedBy = "gate";
    } else if (gateReason !== "") {
      v.reason = gateReason;
    }

    // Veto: a gate-admitted source the checker says contradicts the claim.
    if (v.supported && checker !== null) {
      const kept: string[] = [];
      for (const id of v.sources) {
        const s = await check(text, unitAt(id));
        if (s.contradicted < contradictAt) kept.push(id);
      }
      v.sources = kept;
      if (kept.length === 0) {
        v.supported = false;
        v.verifiedBy = "";
        v.reason = REASON_CONTRADICTED;
      }
    }

    // 2 + 3 + 4. Model-backed admission: cited claims only, checker required,
    // every admission behind the deterministic guards.
    if (!v.supported && v.reason !== REASON_CONTRADICTED && checker !== null && pc.cited.length > 0) {
      let guardReason = "";
      const admit = async (eu: EvidenceUnit): Promise<boolean> => {
        if (!considered.has(eu.id)) {
          considered.add(eu.id);
          scoredOrder.push(eu.id);
        }
        const score = async (): Promise<SupportScores> => {
          const s = await check(text, eu);
          scoredOf.set(eu.id, s);
          return s;
        };
        if (eagerScoring) await score();
        let reason = guards(text, declared, eu, cfg);
        if (reason === "" && pc.item !== "") reason = truncationGuard(stripMarkup(pc.item), eu.text);
        if (reason !== "") {
          if (guardReason === "") guardReason = reason;
          if (!guardOf.has(eu.id)) guardOf.set(eu.id, reason);
          if (!eagerScoring) deferred.set(eu.id, eu);
          return false;
        }
        let s = scoredOf.get(eu.id);
        if (!eagerScoring || s === undefined) s = await score();
        return s.entailed >= entailAt && s.contradicted < contradictAt;
      };

      // 2. QUOTE: every quote in the claim passes the gate against the unit.
      const qs = quotes(text);
      if (qs.length > 0) {
        for (const eu of candidates) {
          const anchored = qs.every((q) => isSupportedV2(q, eu.text) && clauseNegationGuard(q, eu.text) === "");
          if (!anchored) continue;
          if (await admit(eu)) v.sources.push(eu.id);
        }
        if (v.sources.length > 0) {
          v.supported = true;
          v.verifiedBy = "quote+" + modelLabel;
          v.reason = "";
        }
      }

      // 3. MODEL: cross-language, or any language under admitParaphrase.
      if (!v.supported) {
        for (const eu of candidates) {
          const pl = primaryLanguage(eu.language);
          const crossLanguage = claimLanguage !== "" && pl !== "" && pl !== claimLanguage;
          if (!crossLanguage && opts.admitParaphrase !== true) continue;
          if (await admit(eu)) v.sources.push(eu.id);
        }
        if (v.sources.length > 0) {
          v.supported = true;
          v.verifiedBy = modelLabel;
          v.reason = "";
        }
      }

      // 4. UNION: a list item joined to a content lead-in citing different units.
      let unionReason = "";
      let unionGuard = "";
      let unionAllGuarded = true;
      let unionPairs = 0;
      const unionScored = new Map<string, SupportScores>();
      const deferredPairs: [EvidenceUnit, EvidenceUnit][] = [];
      if (!v.supported && pc.lead !== "" && pc.itemCited.length > 0) {
        const lead = stripMarkup(pc.lead);
        const item = stripMarkup(pc.item);
        const inItem = new Set(pc.itemCited);
        const inLead = new Map<string, boolean>();
        for (const id of pc.leadCited) inLead.set(id, !inItem.has(id));
        const allowed = (eu: EvidenceUnit): boolean => {
          const pl = primaryLanguage(eu.language);
          return opts.admitParaphrase === true || (claimLanguage !== "" && pl !== "" && pl !== claimLanguage);
        };
        for (const b of candidates) {
          if (!inItem.has(b.id) || !allowed(b)) continue;
          for (const a of candidates) {
            if (inLead.get(a.id) !== true || !allowed(a)) continue;
            unionPairs++;
            const reason = unionRefusal(text, lead, item, declared, a, b, cfg);
            if (reason !== "" && !eagerScoring) {
              if (unionGuard === "") unionGuard = reason;
              deferredPairs.push([a, b]);
              continue;
            }
            let modelReason = "";
            const premise = unionPremise(a, b);
            for (const p of [a, b, premise]) {
              const s = await check(text, p);
              if (p.id === premise.id) unionScored.set(a.id + "+" + b.id, s);
              if (modelReason !== "") continue;
              if (s.contradicted >= contradictAt) modelReason = REASON_CONTRADICTED;
              else if (p.id === premise.id && s.entailed < entailAt) modelReason = REASON_NOT_SUPPORTED;
            }
            if (reason !== "") {
              if (unionGuard === "") unionGuard = reason;
              continue;
            }
            unionAllGuarded = false;
            if (modelReason !== "") {
              if (unionReason === "") unionReason = modelReason;
              continue;
            }
            v.sources = appendUnique(v.sources, a.id, b.id);
          }
        }
        if (v.sources.length > 0) {
          v.supported = true;
          v.verifiedBy = modelLabel;
          v.reason = "";
        }
      }
      if (!v.supported && unionReason === REASON_CONTRADICTED) v.reason = REASON_CONTRADICTED;
      // A joined claim checked as a union is decided by its pairs.
      if (!v.supported && unionPairs > 0 && v.reason !== REASON_CONTRADICTED) {
        guardOf = new Map();
        scoredOf = new Map();
        scoredOrder = [];
        reasonUnits = [{ id: "union", documentId: "", text: "", language: "" }];
        if (unionAllGuarded) {
          guardOf.set("union", unionGuard);
        } else {
          for (const [a, b] of deferredPairs) {
            unionScored.set(a.id + "+" + b.id, await check(text, unionPremise(a, b)));
          }
          for (const [label, sc] of unionScored) {
            scoredOf.set(label, sc);
            scoredOrder.push(label);
          }
          scoredOrder.sort(cmpGo);
        }
      }
    }

    // F0 — an honest reason. A guard is named only when EVERY cited unit failed
    // a guard; otherwise the MODEL refused, with the best scores over every
    // scored unit. Reporting only: nothing is admitted or refused here.
    if (!v.supported && v.reason !== REASON_CONTRADICTED && reasonUnits.length > 0) {
      const allGuarded = reasonUnits.every((eu) => guardOf.has(eu.id));
      if (!allGuarded && deferred.size > 0 && (reasonUnits[0] as EvidenceUnit).id !== "union") {
        for (const id of scoredOrder) {
          const eu = deferred.get(id);
          if (eu === undefined || scoredOf.has(id)) continue;
          scoredOf.set(id, await check(text, eu));
        }
      }
      if (allGuarded) {
        v.reason = guardOf.get((reasonUnits[0] as EvidenceUnit).id) as string;
      } else if (scoredOf.size > 0) {
        const order = scoredOrder.filter((id) => scoredOf.has(id));
        let best = order[0] as string;
        for (const id of order.slice(1)) {
          const b = scoredOf.get(best) as SupportScores;
          const s = scoredOf.get(id) as SupportScores;
          if (s.entailed > b.entailed || (s.entailed === b.entailed && s.contradicted < b.contradicted)) best = id;
        }
        const bs = scoredOf.get(best) as SupportScores;
        const g = guardOf.get(best);
        const note = g !== undefined ? "; " + best + " refused by " + g : "";
        v.reason = `${REASON_NOT_SUPPORTED} (model: best entailment ${fmt3(bs.entailed)}, contradiction ${fmt3(bs.contradicted)} on ${best}${note})`;
      } else {
        v.reason = REASON_NOT_SUPPORTED;
      }
    }

    if (!v.supported && v.reason === "") v.reason = REASON_NOT_SUPPORTED;
    verdicts.push(v);
  }

  // Conflicts: every unit supporting a surviving claim against every other
  // selected unit (ADR-0007 — it reports, and authority resolves).
  interface Conflict {
    supporting: EvidenceUnit;
    other: EvidenceUnit;
    finding: ConflictFinding;
  }
  const conflicts: Conflict[] = [];
  const checked = new Set<string>();
  for (const v of verdicts) {
    for (const id of v.sources) {
      const s = unitAt(id);
      for (const o of selected) {
        if (o.id === s.id || checked.has(`${s.id}\u0000${o.id}`)) continue;
        checked.add(`${s.id}\u0000${o.id}`);
        checked.add(`${o.id}\u0000${s.id}`);
        const f = detectConflict(s.text, o.text, { leftLanguage: s.language, rightLanguage: o.language });
        if (f !== null) conflicts.push({ supporting: s, other: o, finding: f });
      }
    }
  }
  // A unit loses when something at least as authoritative contradicts it.
  interface Effect {
    outranked: boolean;
    c: Conflict;
    diffRuns: Set<string> | null;
  }
  const effects = new Map<string, Effect[]>();
  const addEffect = (id: string, e: Effect): void => {
    const list = effects.get(id);
    if (list === undefined) effects.set(id, [e]);
    else list.push(e);
  };
  const conflictNotes: string[] = [];
  for (const c of conflicts) {
    const ts = tierOf(c.supporting);
    const to = tierOf(c.other);
    let note = `${c.finding.rule}: ${c.supporting.documentId} vs ${c.other.documentId} (${c.finding.detail})`;
    const runs = c.finding.rule === "value" ? differingDigitRuns(c.supporting, c.other) : null;
    if (tierOutranks(to, ts)) {
      addEffect(c.supporting.id, { outranked: true, c, diffRuns: runs });
      note += ` — resolved by authority: ${c.other.id} outranks ${c.supporting.id}`;
    } else if (tierOutranks(ts, to)) {
      addEffect(c.other.id, { outranked: true, c, diffRuns: runs });
      note += ` — resolved by authority: ${c.supporting.id} outranks ${c.other.id}`;
    } else {
      const e = { outranked: false, c, diffRuns: runs };
      addEffect(c.supporting.id, e);
      addEffect(c.other.id, e);
    }
    conflictNotes.push(note);
  }
  let conflictDropped = 0;
  const unresolvedSides: EvidenceUnit[] = [];
  for (const v of verdicts) {
    if (!v.supported) continue;
    const kept: string[] = [];
    let reason = "";
    for (const id of v.sources) {
      let applied = false;
      for (const e of effects.get(id) ?? []) {
        if (spared(v, e.diffRuns)) continue;
        applied = true;
        if (e.outranked) {
          reason = REASON_OUTRANKED;
        } else {
          if (reason === "") reason = REASON_UNRESOLVED_CLAIMS;
          unresolvedSides.push(e.c.supporting, e.c.other);
        }
      }
      if (!applied) kept.push(id);
    }
    v.sources = kept;
    if (kept.length === 0) {
      v.supported = false;
      v.verifiedBy = "";
      v.reason = reason;
      conflictDropped++;
    }
  }

  // Assemble.
  const answered: string[] = [];
  const claims: Claim[] = [];
  const sources: SourceRef[] = [];
  const cited = new Set<string>();
  const supportingTexts: string[] = [];
  const supportingLanguages: string[] = [];
  let top: EvidenceUnit | null = null;
  let modelVerified = 0;
  for (const v of verdicts) {
    let claimSources: string[] = [];
    if (v.supported) {
      answered.push(v.text);
      claimSources = v.sources;
      if (v.verifiedBy.startsWith("model")) modelVerified++;
      for (const id of v.sources) {
        if (cited.has(id)) continue;
        cited.add(id);
        const eu = unitAt(id);
        supportingTexts.push(eu.text);
        supportingLanguages.push(eu.language);
        sources.push(sourceRefOf(eu));
        if (top === null || tierOutranks(tierOf(eu), tierOf(top))) top = eu;
      }
    }
    claims.push(claimOf(v.text, v.supported, claimSources, v.verifiedBy, v.reason));
  }
  const removed = verdicts.length - answered.length;

  // Facets no verified claim answers are NAMED, never silently missing.
  const covered = new Set<string>();
  for (const v of verdicts) if (v.supported) for (const f of v.facets) covered.add(f);
  const missingFacets: string[] = [];
  const missingFacetNotes: string[] = [];
  for (const f of opts.facets ?? []) {
    if (covered.has(f.id)) continue;
    missingFacets.push(f.id);
    missingFacetNotes.push("no verified answer for: " + (f.label ? f.label : f.id));
  }

  if (answered.length === 0) {
    let refusedAnswer = REFUSAL_ANSWER;
    let missing = ["generated answer failed the faithfulness gate"];
    const refusedSources: SourceRef[] = [];
    if (verdicts.length === 0) {
      missing = ["the answer contains no claims"];
    } else if (conflictDropped > 0 && unresolvedSides.length > 0) {
      // The evidence is there and it disagrees with itself: cite both sides.
      refusedAnswer = CONFLICT_REFUSAL_ANSWER;
      missing = [REASON_UNRESOLVED_CLAIMS];
      const seen = new Set<string>();
      for (const eu of unresolvedSides) {
        if (seen.has(eu.id)) continue;
        seen.add(eu.id);
        refusedSources.push(sourceRefOf(eu));
      }
    } else if (selection.floorApplied && selected.length === 0) {
      missing = [INSUFFICIENT_AUTHORITY];
    }
    return {
      answer: refusedAnswer,
      answer_language: answerLanguage,
      mode: TrustMode.strict,
      evidence: signals({
        decision: Decision.refused,
        supportingSources: 0,
        distinctDocuments: 0,
        allClaimsVerified: false,
        unsupportedClaimsRemoved: removed,
        conflictsDetected: conflicts.length,
        languagesInEvidence: languages,
        unsupportedScripts: unsupported,
        authorityTier: "",
        authorityFloorApplied: selection.floorApplied,
        modelVerifiedClaims: 0,
        missingFacets,
      }),
      claims,
      sources: refusedSources,
      missing_evidence: [...missing, ...missingFacetNotes],
      conflicts: conflictNotes,
      provenance: [],
    };
  }

  const distinct = new Set(sources.map((s) => s.document));
  // Anything dropped or uncovered makes the answer PARTIAL.
  const missing: string[] = [];
  if (unresolvedSides.length > 0) missing.push(REASON_UNRESOLVED_CLAIMS);
  for (const v of verdicts) if (!v.supported) missing.push(`dropped: ${v.text} (${v.reason})`);
  missing.push(...missingFacetNotes);
  const decision = removed > 0 || missingFacets.length > 0 ? Decision.partial : Decision.answered;
  return {
    answer: answered.join(" "),
    answer_language: answerLanguage,
    mode: TrustMode.strict,
    evidence: signals({
      decision,
      supportingSources: collapseNearDuplicates(supportingTexts, supportingLanguages).length,
      distinctDocuments: distinct.size,
      allClaimsVerified: removed === 0,
      unsupportedClaimsRemoved: removed,
      conflictsDetected: conflicts.length,
      languagesInEvidence: languages,
      unsupportedScripts: unsupported,
      authorityTier: top !== null ? tierOf(top).name : "",
      authorityFloorApplied: selection.floorApplied,
      modelVerifiedClaims: modelVerified,
      missingFacets,
    }),
    claims,
    sources,
    missing_evidence: missing,
    conflicts: conflictNotes,
    provenance: [],
  };
}

/** EvidenceSignals in the Go field order; the Go-first fields are omitted when
 * empty (omitempty), so an existing Result serializes unchanged. */
function signals(o: {
  decision: Decision;
  supportingSources: number;
  distinctDocuments: number;
  allClaimsVerified: boolean;
  unsupportedClaimsRemoved: number;
  conflictsDetected: number;
  languagesInEvidence: string[];
  unsupportedScripts: string[];
  authorityTier: string;
  authorityFloorApplied: boolean;
  modelVerifiedClaims: number;
  missingFacets: string[];
}): EvidenceSignals {
  const e: EvidenceSignals = {
    decision: o.decision,
    supporting_sources: o.supportingSources,
    distinct_documents: o.distinctDocuments,
    retrieval_score_spread: 0,
    all_claims_verified: o.allClaimsVerified,
    unsupported_claims_removed: o.unsupportedClaimsRemoved,
    conflicts_detected: o.conflictsDetected,
    languages_in_evidence: o.languagesInEvidence,
    unsupported_scripts: o.unsupportedScripts,
    authority_tier: o.authorityTier,
    authority_floor_applied: o.authorityFloorApplied,
  } as EvidenceSignals;
  if (o.modelVerifiedClaims !== 0) e.model_verified_claims = o.modelVerifiedClaims;
  if (o.missingFacets.length > 0) e.missing_facets = o.missingFacets;
  e.loop = null;
  return e;
}

function claimOf(text: string, supported: boolean, sources: string[], verifiedBy: string, reason: string): Claim {
  const c: Claim = { claim: text, supported, sources };
  if (verifiedBy !== "") c.verified_by = verifiedBy;
  if (reason !== "") c.reason = reason;
  return c;
}

const DIGIT_RUN = /[0-9]+/g;

/** The digit runs of every number one unit carries and the other does not (by
 * ADR-0015 key), from both sides. */
function differingDigitRuns(a: EvidenceUnit, b: EvidenceUnit): Set<string> {
  const runs = new Set<string>();
  const collect = (x: EvidenceUnit, y: EvidenceUnit): void => {
    const have = new Set(numbersIn(y.text, y.language).map((m) => m.reading.key));
    for (const m of numbersIn(x.text, x.language)) {
      if (have.has(m.reading.key)) continue;
      for (const run of m.raw.match(DIGIT_RUN) ?? []) runs.add(run);
    }
  };
  collect(a, b);
  collect(b, a);
  return runs;
}

/** A VALUE conflict provably does not touch this claim: verified on its own
 * words and carrying none of the differing digit runs. */
function spared(v: Verdict, diffRuns: ReadonlySet<string> | null): boolean {
  if (diffRuns === null) return false;
  if (v.verifiedBy !== "gate" && !v.verifiedBy.startsWith("quote+")) return false;
  for (const run of v.text.match(DIGIT_RUN) ?? []) if (diffRuns.has(run)) return false;
  return true;
}

function sourceRefOf(eu: EvidenceUnit): SourceRef {
  return sourceRef({
    document: eu.documentId,
    passage: eu.text,
    passageLanguage: eu.language === "" ? UNDECLARED_LANGUAGE : eu.language,
  });
}
