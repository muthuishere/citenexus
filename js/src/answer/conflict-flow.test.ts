// ADR-0007 end to end: an unresolved conflict touching the answer's own claim
// is an ABSTENTION in strict mode, citing both sides — and differing numbers on
// their own are NOT a conflict.
//
// The two corpora below are the same ones the Python and Go ports are held to.
// The negative case is the load-bearing half: `MAX_RESIDUAL = 1` is what keeps
// "Q1 was 12 cents" / "Q2 was 15 cents" an answer instead of a false refusal,
// and in strict mode a false conflict is a false refusal.

import { describe, expect, it } from "vitest";

import { Decision } from "../result/result.js";
import { ask, askWith, CONFLICT_REFUSAL_ANSWER, type CorpusDoc } from "./answer.js";

const CONFLICTING: CorpusDoc[] = [
  { document_id: "filing-q1", text: "The dividend for the period was 12 cents per share." },
  {
    document_id: "filing-q1-restated",
    text: "The dividend for the period was 30 cents per share.",
  },
];
const CONFLICT_QUESTION = "What was the dividend per share for the period?";

const COMPLEMENTARY: CorpusDoc[] = [
  { document_id: "filing-q1", text: "The Q1 dividend was 12 cents per share." },
  { document_id: "filing-q2", text: "The Q2 dividend was 15 cents per share." },
];
const COMPLEMENTARY_QUESTION = "What was the Q1 dividend per share?";

describe("strict-mode conflict abstention", () => {
  it("refuses, and cites BOTH sides of the disagreement", () => {
    const r = ask(CONFLICTING, CONFLICT_QUESTION);

    expect(r.evidence.decision).toBe(Decision.refused);
    expect(r.answer).toBe(CONFLICT_REFUSAL_ANSWER);
    expect(r.answer).toBe("The available evidence disagrees, so I can't answer that.");
    expect(r.evidence.conflicts_detected).toBe(1);

    // Neither passage is named the winner: both are returned, verbatim.
    expect(r.sources.map((s) => s.document)).toEqual(["filing-q1", "filing-q1-restated"]);
    expect(r.sources.map((s) => s.passage)).toEqual(CONFLICTING.map((d) => d.text));

    expect(r.conflicts).toEqual(["value: filing-q1 vs filing-q1-restated (12 vs 30)"]);
    expect(r.missing_evidence).toEqual(["cited sources disagree and the conflict is unresolved"]);
    // A refusal makes no claim, so it carries none.
    expect(r.claims).toEqual([]);
  });

  it("askWith reaches the identical Result", async () => {
    expect(await askWith(CONFLICTING, CONFLICT_QUESTION)).toEqual(ask(CONFLICTING, CONFLICT_QUESTION));
  });
});

describe("differing numbers alone are not a conflict", () => {
  it("answers, with no conflict detected", () => {
    const r = ask(COMPLEMENTARY, COMPLEMENTARY_QUESTION);

    expect(r.evidence.decision).toBe(Decision.answered);
    expect(r.evidence.conflicts_detected).toBe(0);
    expect(r.conflicts).toEqual([]);
    expect(r.answer).not.toBe(CONFLICT_REFUSAL_ANSWER);
    expect(r.sources).toHaveLength(1);
    expect(r.sources[0]!.document).toBe("filing-q1");
  });

  it("askWith reaches the identical Result", async () => {
    expect(await askWith(COMPLEMENTARY, COMPLEMENTARY_QUESTION)).toEqual(
      ask(COMPLEMENTARY, COMPLEMENTARY_QUESTION),
    );
  });
});
