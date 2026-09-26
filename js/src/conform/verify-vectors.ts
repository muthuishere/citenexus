// The verify_answer.json vector shape and the fake checker the Go loader
// (golang/answer/verify_answer_conformance_test.go) drives it with — shared by
// the conformance test and the lazy-vs-eager scoring test. Test-only: src/conform
// is excluded from the build.
import type { SupportChecker, SupportScores } from "../contracts.js";
import { DEFAULT_ACTOR_LEXICON, withActorTerms } from "../answer/verify-roles.js";
import type { ActorLexicon } from "../answer/verify-roles.js";
import type { GlossaryEntry } from "../answer/glossary.js";
import { unionPremise } from "../answer/verify-union.js";
import type { EvidenceUnit, VerifyOptions } from "../answer/verify-answer.js";

export interface WireUnit {
  id: string;
  document_id: string;
  language: string;
  text: string;
}

export interface VerifyVector {
  name: string;
  must_refuse?: boolean;
  answer: string;
  answer_language?: string;
  admit_paraphrase?: boolean;
  name_aliases?: Record<string, string[]>;
  checker?: Record<string, number[]>;
  checker_claims?: Record<string, Record<string, number[]>>;
  lead_in_frames?: string[];
  actors?: Record<string, string[]>;
  glossary?: [string, string][];
  conjunct_presence?: boolean;
  glossary_entries?: {
    nl: string;
    en: string;
    lemma_nl?: string;
    lemma_en?: string;
    sep?: string;
    class?: string;
  }[];
  evidence: WireUnit[];
  expect: {
    decision: string;
    conflicts_reported?: boolean;
    claims: { supported: boolean; reason: string }[];
  };
}

/** Scores by passage (a unit's text, or a union premise), and by (claim, passage)
 * where a vector pins one claim — golang's idChecker. */
export class IdChecker implements SupportChecker {
  byPassage = new Map<string, [number, number]>();
  byClaim = new Map<string, [number, number]>();
  calls = 0;
  check(claim: string, passage: string): Promise<SupportScores> {
    this.calls++;
    const [entailed, contradicted] =
      this.byClaim.get(`${claim}\u0000${passage}`) ?? this.byPassage.get(passage) ?? [0, 0];
    return Promise.resolve({ entailed, contradicted });
  }
}

export function vectorEvidence(c: VerifyVector): EvidenceUnit[] {
  return c.evidence.map((e) => ({
    id: e.id,
    documentId: e.document_id,
    language: e.language,
    text: e.text,
  }));
}

/** The options a vector drives, with its checker (when it declares scores). */
export function vectorOptions(c: VerifyVector, evidence: EvidenceUnit[]): {
  opts: VerifyOptions;
  checker: IdChecker;
} {
  const byID = new Map(evidence.map((e) => [e.id, e]));
  const premise = (key: string): string => {
    const plus = key.indexOf("+");
    if (plus >= 0) {
      return unionPremise(
        byID.get(key.slice(0, plus)) ?? emptyUnit(),
        byID.get(key.slice(plus + 1)) ?? emptyUnit(),
      ).text;
    }
    return byID.get(key)?.text ?? "";
  };
  const checker = new IdChecker();
  for (const [key, s] of Object.entries(c.checker ?? {})) {
    checker.byPassage.set(premise(key), [s[0] ?? 0, s[1] ?? 0]);
  }
  for (const [key, claims] of Object.entries(c.checker_claims ?? {})) {
    for (const [claim, s] of Object.entries(claims)) {
      checker.byClaim.set(`${claim}\u0000${premise(key)}`, [s[0] ?? 0, s[1] ?? 0]);
    }
  }
  const opts: VerifyOptions = {
    answerLanguage: c.answer_language ?? "",
    admitParaphrase: c.admit_paraphrase ?? false,
    conjunctPresence: c.conjunct_presence ?? false,
  };
  if (c.name_aliases !== undefined) opts.nameAliases = c.name_aliases;
  if (c.lead_in_frames !== undefined && c.lead_in_frames !== null) opts.leadInFrames = c.lead_in_frames;
  if (c.glossary !== undefined && c.glossary !== null) opts.glossary = c.glossary;
  if (c.glossary_entries !== undefined && c.glossary_entries !== null) {
    opts.glossaryEntries = c.glossary_entries.map(
      (e): GlossaryEntry => ({
        nl: e.nl,
        en: e.en,
        lemmaNL: e.lemma_nl ?? "",
        lemmaEN: e.lemma_en ?? "",
        sep: e.sep ?? "",
        class: e.class ?? "",
      }),
    );
  }
  if (c.actors !== undefined && Object.keys(c.actors).length > 0) {
    let lexicon: ActorLexicon = DEFAULT_ACTOR_LEXICON;
    for (const [id, terms] of Object.entries(c.actors)) lexicon = withActorTerms(lexicon, id, ...terms);
    opts.actors = lexicon;
  }
  if (Object.keys(c.checker ?? {}).length > 0 || Object.keys(c.checker_claims ?? {}).length > 0) {
    opts.checker = checker;
    opts.checkerName = "fake";
  }
  return { opts, checker };
}

function emptyUnit(): EvidenceUnit {
  return { id: "", documentId: "", language: "", text: "" };
}

