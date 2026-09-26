// conformance/cases/verify_answer.json and heading_check.json — the VerifyAnswer
// contract every port must meet. Mirrors golang/answer/verify_answer_conformance_test.go
// and golang/answer/heading_test.go case for case: the same fake checker, the same
// options, the same assertions, the same count.
import { describe, expect, it } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import { Decision } from "../result/result.js";
import type { SupportChecker, SupportScores } from "../contracts.js";
import {
  headingNameUnsupported,
  headingNeedsCheck,
  headingNeedsCheckWith,
} from "./heading.js";
import { DEFAULT_ACTOR_LEXICON, withActorTerms } from "./verify-roles.js";
import type { ActorLexicon } from "./verify-roles.js";
import type { GlossaryEntry } from "./glossary.js";
import { unionPremise } from "./verify-union.js";
import { verifyAnswer } from "./verify-answer.js";
import type { EvidenceUnit, VerifyOptions } from "./verify-answer.js";

interface WireUnit {
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

const verifyFile = loadCase<{ cases: VerifyVector[] }>("verify_answer.json");

describe("verify_answer.json", () => {
  it("has 325 cases and at least 5 must-refuse controls", () => {
    expect(verifyFile.cases.length).toBe(325);
    expect(verifyFile.cases.filter((c) => c.must_refuse === true).length).toBeGreaterThanOrEqual(5);
  });

  for (const c of verifyFile.cases) {
    it(c.name, async () => {
      const evidence = vectorEvidence(c);
      const { opts } = vectorOptions(c, evidence);
      const res = await verifyAnswer(c.answer, evidence, opts);
      const claims = JSON.stringify(res.claims);
      expect(res.evidence.decision, `claims ${claims}`).toBe(c.expect.decision);
      if (c.expect.conflicts_reported === true) {
        expect(res.conflicts.length, "the conflict must still be REPORTED").toBeGreaterThan(0);
      }
      expect(res.claims.length, claims).toBe(c.expect.claims.length);
      c.expect.claims.forEach((want, i) => {
        const got = res.claims[i];
        const ok =
          got !== undefined &&
          got.supported === want.supported &&
          (got.reason ?? "").startsWith(want.reason);
        expect(
          ok,
          `claim ${i}: supported=${String(got?.supported)} reason=${JSON.stringify(got?.reason ?? "")}, ` +
            `want supported=${String(want.supported)} reason prefix ${JSON.stringify(want.reason)}`,
        ).toBe(true);
      });
      if (c.must_refuse === true) {
        expect(res.evidence.decision, "must-refuse control was answered").not.toBe(Decision.answered);
      }
    });
  }
});

interface HeadingVector {
  name: string;
  must_refuse?: boolean;
  heading: string;
  language: string;
  cite?: string;
  evidence: WireUnit[];
  expect: { needs_check: boolean; reason: string; name_reason: string; outcome: string };
}

const headingFile = loadCase<{ cases: HeadingVector[] }>("heading_check.json");

describe("heading_check.json", () => {
  it("has 14 cases and at least 3 must-refuse controls", () => {
    expect(headingFile.cases.length).toBe(14);
    expect(headingFile.cases.filter((c) => c.must_refuse === true).length).toBeGreaterThanOrEqual(3);
  });

  for (const c of headingFile.cases) {
    it(c.name, async () => {
      const evidence: EvidenceUnit[] = c.evidence.map((e) => ({
        id: e.id,
        documentId: e.document_id,
        language: e.language,
        text: e.text,
      }));
      const [claim, reason] = headingNeedsCheck(c.heading, c.language);
      const want = c.expect;
      expect(
        claim === want.needs_check && reason.startsWith(want.reason) && !(want.reason === "" && reason !== ""),
        `headingNeedsCheck = ${String(claim)} ${JSON.stringify(reason)}, want ${String(want.needs_check)} ${JSON.stringify(want.reason)}`,
      ).toBe(true);
      const nameReason = headingNameUnsupported(c.heading, evidence, null);
      expect(
        nameReason.startsWith(want.name_reason) && !(want.name_reason === "" && nameReason !== ""),
        `headingNameUnsupported = ${JSON.stringify(nameReason)}, want ${JSON.stringify(want.name_reason)}`,
      ).toBe(true);
      let answer = c.heading;
      if (c.cite !== undefined && c.cite !== "") answer += " [eu:" + c.cite + "]";
      const res = await verifyAnswer(answer, evidence, {
        answerLanguage: c.language,
        requireCitations: true,
      });
      expect(res.claims.length, JSON.stringify(res.claims)).toBe(1);
      let outcome = "exempt";
      if (res.claims[0]?.supported === true) outcome = "admitted";
      else if (claim || nameReason !== "") outcome = "refused";
      expect(outcome, JSON.stringify(res.claims[0])).toBe(want.outcome);
      if (c.must_refuse === true) expect(outcome).toBe("refused");
    });
  }

  it("heading rules are injectable", () => {
    const rules = { modals: { nl: ["dient"] } };
    expect(headingNeedsCheckWith("Wat de werknemer dient te doen", "nl", rules)[0]).toBe(true);
    expect(headingNeedsCheckWith("De werknemer moet betalen", "nl", rules)[0]).toBe(false);
  });
});
