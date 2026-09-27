// conformance/cases/verify_answer.json and heading_check.json — the VerifyAnswer
// contract every port must meet. Mirrors golang/answer/verify_answer_conformance_test.go
// and golang/answer/heading_test.go case for case: the same fake checker, the same
// options, the same assertions, the same count.
import { describe, expect, it } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import { Decision } from "../result/result.js";
import {
  headingNameUnsupported,
  headingNeedsCheck,
  headingNeedsCheckWith,
} from "./heading.js";
import { vectorEvidence, vectorOptions } from "../conform/verify-vectors.js";
import type { VerifyVector, WireUnit } from "../conform/verify-vectors.js";
import { verifyAnswer } from "./verify-answer.js";
import type { EvidenceUnit } from "./verify-answer.js";

const verifyFile = loadCase<{ cases: VerifyVector[] }>("verify_answer.json");

describe("verify_answer.json", () => {
  it("has 346 cases and at least 5 must-refuse controls", () => {
    expect(verifyFile.cases.length).toBe(346);
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
