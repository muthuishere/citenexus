// The nine adversarial false answers, driven through the FLOW — not through the
// predicate.
//
// `spikes/library-stress/ports/js/probe-a.mjs` already ran these nine against
// `isSupportedV2` and reported 0/9 accepted. That proved the FUNCTION was sound
// and nothing at all about `askWith`, which was still calling the frozen v1
// predicate. A probe that can pass while the shipped path is broken is the
// "green suite as camouflage" failure ADR-0014 documents, so the assertion that
// matters lives here, on the path a caller actually reaches.
//
// Each case is one corpus document (the true passage) plus a generator that
// returns the falsified answer. The question shares content tokens with the
// passage, so retrieval and the relevance gate both pass and the ONLY thing
// standing between the lie and the caller is the faithfulness gate.

import { describe, expect, it } from "vitest";

import type { GeneratorProvider } from "../contracts.js";
import { Decision } from "../result/result.js";
import { ask, askWith, type CorpusDoc } from "./answer.js";

/** A generator that says exactly what it is told to say. */
function saying(reply: string): GeneratorProvider {
  return { answer: () => reply };
}

interface Attack {
  name: string;
  question: string;
  passage: string;
  answer: string;
}

/** The nine attacks, byte-identical to `conformance/cases/faithful_v2.json`. */
const ATTACKS: readonly Attack[] = [
  {
    name: "legal/role-inversion",
    question: "Who shall indemnify whom for damage to the property?",
    passage: "The tenant shall indemnify the landlord for damage to the property.",
    answer: "The landlord shall indemnify the tenant for damage to the property.",
  },
  {
    name: "finance/role-inversion",
    question: "Who pays the fee of 400 basis points?",
    passage: "The borrower pays the lender a fee of 400 basis points.",
    answer: "The lender pays the borrower a fee of 400 basis points.",
  },
  {
    name: "medical/role-inversion",
    question: "Which drug increases the effect of the other in adult patients?",
    passage: "Ibuprofen increases the effect of warfarin in adult patients.",
    answer: "Warfarin increases the effect of ibuprofen in adult patients.",
  },
  {
    name: "legal/negation-deletion",
    question: "May the employee disclose confidential information?",
    passage: "The employee shall not disclose confidential information.",
    answer: "The employee shall disclose confidential information.",
  },
  {
    name: "operations/negation-deletion",
    question: "May the reactor be restarted without a signed safety review?",
    passage: "The reactor must not be restarted without a signed safety review.",
    answer: "The reactor must be restarted without a signed safety review.",
  },
  {
    name: "medical/negation-deletion",
    question: "Is this medication approved for patients under twelve years?",
    passage: "This medication is not approved for patients under twelve years.",
    answer: "This medication is approved for patients under twelve years.",
  },
  {
    name: "finance/value-swap",
    question: "What revenue did region A and region B report?",
    passage: "Region A reported 40 million in revenue and region B reported 12 million.",
    answer: "Region A reported 12 million in revenue and region B reported 40 million.",
  },
  {
    name: "physics/value-swap",
    question: "At what temperature does the sample melt and boil?",
    passage: "The sample melts at 240 kelvin and boils at 610 kelvin.",
    answer: "The sample melts at 610 kelvin and boils at 240 kelvin.",
  },
  {
    name: "physics/comparator-inversion",
    question: "Which chamber has the greater pressure?",
    passage: "Pressure in chamber one is greater than pressure in chamber two.",
    answer: "Pressure in chamber two is greater than pressure in chamber one.",
  },
];

describe("askWith refuses every adversarial answer", () => {
  for (const attack of ATTACKS) {
    it(`refuses ${attack.name}`, async () => {
      const corpus: CorpusDoc[] = [{ document_id: "d1", text: attack.passage }];
      const res = await askWith(corpus, attack.question, {
        generator: saying(attack.answer),
      });
      // The falsified claim must never reach a caller.
      expect(res.answer).not.toBe(attack.answer);
      expect(res.evidence.decision).toBe(Decision.refused);
    });
  }
});

describe("askWith still answers a verbatim quote", () => {
  // A gate that refuses everything is not a gate: the same flow must still
  // answer when the generator quotes the passage back.
  for (const attack of ATTACKS) {
    it(`answers the true passage for ${attack.name}`, async () => {
      const corpus: CorpusDoc[] = [{ document_id: "d1", text: attack.passage }];
      const res = await askWith(corpus, attack.question, {
        generator: saying(attack.passage),
      });
      expect(res.evidence.decision).toBe(Decision.answered);
      expect(res.answer).toBe(attack.passage);
    });
  }
});

describe("ask answers a verbatim non-Latin quote", () => {
  // The OTHER half of the gate move, driven through the SYNC `ask` flow so the
  // duplicated copy is covered too.
  //
  // The v1 gates run on the v1 ASCII tokenizer, under which a Japanese (or
  // Greek, or Devanagari) question and its own passage BOTH tokenize to the
  // empty set: the relevance gate found no shared token and the flow abstained
  // before the faithfulness gate ever ran, so this port refused every non-Latin
  // question no matter how perfectly the evidence answered it. V2 tokenizes 14
  // scripts (ADR-0011), so a verbatim quote is accepted here exactly as it
  // already is in Latin script. Behaviour change, not just a bug fix — the ports
  // are no longer ASCII-only on the ask path.
  const cases: readonly { name: string; question: string; passage: string }[] = [
    { name: "japanese", question: "保証期間は何年ですか", passage: "保証期間は二年です" },
    { name: "greek", question: "Ποια είναι η εγγύηση", passage: "Η εγγύηση διαρκεί δύο χρόνια" },
    { name: "hindi", question: "वारंटी कितने साल की है", passage: "वारंटी दो साल की है" },
    { name: "russian", question: "Какая гарантия", passage: "Гарантия составляет два года" },
  ];
  for (const tc of cases) {
    it(`answers in ${tc.name}`, () => {
      const res = ask([{ document_id: "d1", text: tc.passage }], tc.question);
      expect(res.evidence.decision).toBe(Decision.answered);
      expect(res.answer).toBe(tc.passage);
    });
  }
});
