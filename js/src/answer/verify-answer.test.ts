// Ports of the Go unit tests that pin verifyAnswer beyond the conformance
// vectors: golang/answer/verify_answer_test.go, verify_number_forms_test.go,
// verify_union_reason_test.go, verify_parties_binding_test.go,
// verify_premise_invariance_test.go and glossary_bench_test.go (its
// concurrency check; the allocation bound and benchmarks are Go-only).
import { describe, expect, it } from "vitest";
import { isSupportedV2 } from "../gate/verify-v2.js";
import { AuthorityPolicy, INSUFFICIENT_AUTHORITY } from "../authority/authority.js";
import { loadCase } from "../conform/fixtures.js";
import type { SupportChecker, SupportScores } from "../contracts.js";
import { Decision, claim as makeClaim } from "../result/result.js";
import type { Result } from "../result/result.js";
import { CONFLICT_REFUSAL_ANSWER } from "./answer.js";
import { parseGlossaryTSV, prepareGlossary } from "./glossary.js";
import type { GlossaryEntry, PreparedGlossary } from "./glossary.js";
import { vectorEvidence, vectorOptions } from "../conform/verify-vectors.js";
import type { VerifyVector } from "../conform/verify-vectors.js";
import {
  InvalidEvidenceError,
  REASON_CONTRADICTED,
  REASON_BELOW_FLOOR,
  REASON_NOT_SUPPORTED,
  REASON_OUTRANKED,
  REASON_UNCITED,
  REASON_UNKNOWN_CITATION,
  REASON_UNRESOLVED_CLAIMS,
  parseCitations,
  verifyAnswer,
  verifyAnswerInternal,
} from "./verify-answer.js";
import type { EvidenceUnit, VerifyOptions } from "./verify-answer.js";
import { exclusionGuard } from "./verify-exclusions.js";
import { names, numberGuard } from "./verify-guards.js";
import type { GuardConfig } from "./verify-guards.js";
import { DEFAULT_QUALIFIER_PAIRS } from "./verify-qualifier-pairs.js";
import { DEFAULT_ACTOR_LEXICON, EMPTY_ACTOR_LEXICON } from "./verify-roles.js";
import { DEFAULT_SUBTYPE_HEADS } from "./verify-subtypes.js";
import { DEFAULT_VERB_PAIRS, verbPairGuard } from "./verify-verbpairs.js";

const notice30: EvidenceUnit = { id: "hr-1#0", documentId: "hr-1", text: "The notice period is 30 days.", language: "en" };
const notice60: EvidenceUnit = { id: "hr-2#0", documentId: "hr-2", text: "The notice period is 60 days.", language: "en" };
const leave: EvidenceUnit = { id: "hr-3#0", documentId: "hr-3", text: "Employees receive 25 days of annual leave.", language: "en" };
const dutchLeave: EvidenceUnit = { id: "nl-1#0", documentId: "nl-1", text: "Werknemers krijgen 25 vakantiedagen per jaar.", language: "nl" };

/** Answers from a table keyed by passage; unknown passages score (0, 0). */
class FakeChecker implements SupportChecker {
  calls = 0;
  constructor(
    readonly scores: Record<string, [number, number]> = {},
    readonly err: Error | null = null,
  ) {}
  check(_claim: string, passage: string): SupportScores {
    this.calls++;
    if (this.err !== null) throw this.err;
    const [entailed, contradicted] = this.scores[passage] ?? [0, 0];
    return { entailed, contradicted };
  }
}

const admitAll: SupportChecker = { check: () => ({ entailed: 0.999, contradicted: 0 }) };
const lowChecker: SupportChecker = { check: () => ({ entailed: 0.1, contradicted: 0.02 }) };

const verify = (answer: string, evidence: EvidenceUnit[], opts: VerifyOptions = {}): Promise<Result> =>
  verifyAnswer(answer, evidence, opts);

function guardConfig(o: Partial<GuardConfig> = {}): GuardConfig {
  return {
    aliases: null,
    actors: DEFAULT_ACTOR_LEXICON,
    pairs: DEFAULT_QUALIFIER_PAIRS,
    verbs: DEFAULT_VERB_PAIRS,
    gloss: null,
    noDefinitions: false,
    docDefs: new Map(),
    subtypes: DEFAULT_SUBTYPE_HEADS,
    fragment: false,
    conjunctPresence: false,
    ...o,
  };
}

describe("parseCitations", () => {
  const cases: [string, string, { text: string; cited: string[]; facets?: string[] }[]][] = [
    ["marker before period", "One fact [eu:a]. Two fact [eu:b].", [{ text: "One fact.", cited: ["a"] }, { text: "Two fact.", cited: ["b"] }]],
    ["marker after period attaches backwards", "One fact. [eu:a] Two fact. [eu:b]", [{ text: "One fact.", cited: ["a"] }, { text: "Two fact.", cited: ["b"] }]],
    ["dotted id does not split", "One fact [eu:doc.pdf#3].", [{ text: "One fact.", cited: ["doc.pdf#3"] }]],
    ["comma list and repeated groups", "One fact [eu:a, eu:b][eu:c, a].", [{ text: "One fact.", cited: ["a", "b", "c"] }]],
    ["uncited", "One fact.", [{ text: "One fact.", cited: [] }]],
    [
      "facet markers are separate from citations",
      "One fact [eu:a][q:cost]. Two fact [q:when, q:who][eu:b].",
      [{ text: "One fact.", cited: ["a"], facets: ["cost"] }, { text: "Two fact.", cited: ["b"], facets: ["when", "who"] }],
    ],
  ];
  for (const [name, answer, want] of cases) {
    it(name, () => {
      const got = parseCitations(answer).map((c) => ({ text: c.text, cited: c.cited, facets: c.facets }));
      expect(got).toEqual(want.map((w) => ({ text: w.text, cited: w.cited, facets: w.facets ?? [] })));
    });
  }
});

describe("verifyAnswer (golang verify_answer_test.go)", () => {
  it("keeps the true half", async () => {
    const res = await verify(
      "The notice period is 30 days [eu:hr-1#0]. The notice period is 90 days [eu:hr-1#0].",
      [notice30, leave],
    );
    expect(res.evidence.decision).toBe(Decision.partial);
    expect(res.answer).toBe("The notice period is 30 days.");
    expect(res.evidence.all_claims_verified).toBe(false);
    expect(res.evidence.unsupported_claims_removed).toBe(1);
    expect(res.claims[0]?.verified_by).toBe("gate");
    expect(res.claims[1]?.reason).toBe(REASON_NOT_SUPPORTED);
    expect(res.sources.map((s) => s.document)).toEqual(["hr-1"]);
  });

  describe("citation rules", () => {
    const ev = [notice30, leave];
    it("unknown id", async () => {
      const res = await verify("The notice period is 30 days [eu:nope].", ev);
      expect(res.evidence.decision).toBe(Decision.refused);
      expect(res.claims[0]?.reason).toBe(REASON_UNKNOWN_CITATION);
    });
    it("wrong citation is not rescued by another unit", async () => {
      const res = await verify("The notice period is 30 days [eu:hr-3#0].", ev);
      expect(res.evidence.decision).toBe(Decision.refused);
    });
    it("uncited is searched by default", async () => {
      const res = await verify("The notice period is 30 days.", ev);
      expect(res.evidence.decision).toBe(Decision.answered);
      expect(res.claims[0]?.sources[0]).toBe("hr-1#0");
    });
    it("uncited is dropped when citations are required", async () => {
      const res = await verify("The notice period is 30 days.", ev, { requireCitations: true });
      expect(res.evidence.decision).toBe(Decision.refused);
      expect(res.claims[0]?.reason).toBe(REASON_UNCITED);
    });
    it("empty answer refuses", async () => {
      const res = await verify("  ", ev);
      expect(res.evidence.decision).toBe(Decision.refused);
      expect(res.missing_evidence).toEqual(["the answer contains no claims"]);
    });
  });

  it("invalid evidence is an error", async () => {
    for (const ev of [[notice30, notice30], [{ id: "", documentId: "", text: "x", language: "" }]]) {
      await expect(verify("x", ev)).rejects.toBeInstanceOf(InvalidEvidenceError);
    }
  });

  it("the support checker vetoes a gate-admitted claim", async () => {
    const checker = new FakeChecker({ [notice30.text]: [0.1, 0.8] });
    const res = await verify("The notice period is 30 days [eu:hr-1#0].", [notice30], { checker });
    expect(res.evidence.decision).toBe(Decision.refused);
    expect(res.claims[0]?.reason).toBe(REASON_CONTRADICTED);
  });

  it("the support checker admits only cross-language claims", async () => {
    const checker = new FakeChecker({ [dutchLeave.text]: [0.97, 0.01], [leave.text]: [0.97, 0.01] });
    const opts: VerifyOptions = { checker, checkerName: "mdeberta", answerLanguage: "en" };
    let res = await verify("Employees get 25 vacation days a year [eu:nl-1#0].", [dutchLeave], opts);
    expect(res.evidence.decision).toBe(Decision.answered);
    expect(res.claims[0]?.verified_by).toBe("model:mdeberta");
    expect(res.evidence.model_verified_claims).toBe(1);
    res = await verify("Staff get 25 vacation days a year [eu:hr-3#0].", [leave], opts);
    expect(res.evidence.decision).toBe(Decision.refused);
    res = await verify("Employees get 25 vacation days a year [eu:nl-1#0].", [dutchLeave], { ...opts, answerLanguage: "" });
    expect(res.evidence.decision).toBe(Decision.refused);
  });

  it("the checker below threshold does not admit", async () => {
    const checker = new FakeChecker({ [dutchLeave.text]: [0.85, 0.01] });
    const res = await verify("Employees get 25 vacation days a year [eu:nl-1#0].", [dutchLeave], {
      checker,
      answerLanguage: "en-GB",
    });
    expect(res.evidence.decision).toBe(Decision.refused);
  });

  it("a checker error is an error", async () => {
    const checker = new FakeChecker({}, new Error("onnx: boom"));
    await expect(verify("The notice period is 30 days [eu:hr-1#0].", [notice30], { checker })).rejects.toThrow(/boom/);
  });

  it("an async checker is awaited", async () => {
    const checker: SupportChecker = {
      check: async (_c, p) => (p === dutchLeave.text ? { entailed: 0.97, contradicted: 0.01 } : { entailed: 0, contradicted: 0 }),
    };
    const res = await verify("Employees get 25 vacation days a year [eu:nl-1#0].", [dutchLeave], {
      checker,
      checkerName: "async",
      answerLanguage: "en",
    });
    expect(res.claims[0]?.verified_by).toBe("model:async");
  });

  it("an equal-authority conflict abstains citing both sides", async () => {
    const res = await verify("The notice period is 30 days [eu:hr-1#0].", [notice30, notice60]);
    expect(res.answer).toBe(CONFLICT_REFUSAL_ANSWER);
    expect(res.evidence.conflicts_detected).toBe(1);
    expect(res.sources.length).toBe(2);
    expect(res.claims[0]?.reason).toBe(REASON_UNRESOLVED_CLAIMS);
  });

  it("higher authority resolves the conflict", async () => {
    const adopted = { ...notice30, authority: { authority_tier: "adopted" } };
    const proposal = { ...notice60, authority: { authority_tier: "proposal" } };
    const policy = AuthorityPolicy.ordered(["proposal", "adopted"]);
    const ev = [proposal, adopted];
    let res = await verify("The notice period is 30 days [eu:hr-1#0].", ev, { authority: policy });
    expect(res.evidence.decision).toBe(Decision.answered);
    expect(res.evidence.authority_tier).toBe("adopted");
    expect(res.conflicts.length).toBe(1);
    expect(res.conflicts[0]).toContain("resolved by authority");
    res = await verify("The notice period is 60 days [eu:hr-2#0].", ev, { authority: policy });
    expect(res.evidence.decision).toBe(Decision.refused);
    expect(res.claims[0]?.reason).toBe(REASON_OUTRANKED);
  });

  it("the authority floor excludes cited evidence", async () => {
    const note = { ...leave, authority: { authority_tier: "note" } };
    const policy = AuthorityPolicy.ordered(["note", "adopted"], "adopted");
    const res = await verify("Employees receive 25 days of annual leave [eu:hr-3#0].", [note], { authority: policy });
    expect(res.evidence.decision).toBe(Decision.refused);
    expect(res.evidence.authority_floor_applied).toBe(true);
    expect(res.claims[0]?.reason).toBe(REASON_BELOW_FLOOR);
    expect(res.missing_evidence[0]).toBe(INSUFFICIENT_AUTHORITY);
  });

  it("the new Result fields are omitted when empty", async () => {
    const raw = JSON.stringify(makeClaim({ claim: "x", supported: true, sources: [] }));
    expect(raw).not.toContain("verified_by");
    expect(raw).not.toContain("reason");
    const res = await verify("The notice period is 30 days [eu:hr-1#0].", [notice30]);
    const wire = JSON.stringify(res.evidence);
    expect(wire).not.toContain("model_verified_claims");
    expect(wire).not.toContain("missing_facets");
    expect(Object.keys(res.evidence).at(-1)).toBe("loop");
  });

  describe("the guards cannot be overridden by the model", () => {
    const sure = new FakeChecker({ [dutchLeave.text]: [0.99, 0.0] });
    const cases: [string, string][] = [
      ["number", "Employees get 30 vacation days a year [eu:nl-1#0]."],
      ["negation", "Employees do not get 25 vacation days a year [eu:nl-1#0]."],
      ["name", "Employees at Acme get 25 vacation days a year [eu:nl-1#0]."],
    ];
    for (const [guard, claim] of cases) {
      it(guard, async () => {
        const res = await verify(claim, [dutchLeave], { checker: sure, answerLanguage: "en" });
        expect(res.evidence.decision).toBe(Decision.refused);
        expect(res.claims[0]?.reason?.startsWith(guard + " guard"), res.claims[0]?.reason).toBe(true);
      });
    }
  });

  it("the number guard reads each side in its language", () => {
    const cases: [string, string, string, string, boolean][] = [
      ["The fee is €25.50.", "en", "De vergoeding is € 25,50.", "nl", true],
      ["The budget is €1,500.", "en", "Het budget is € 1.500.", "nl", true],
      ["De vergoeding is € 25,-.", "nl", "De vergoeding is € 25,00.", "nl", true],
      ["The fee is €25.05.", "en", "De vergoeding is € 25,50.", "nl", false],
      ["The budget is €1.500.", "en", "Het budget is € 1.500.", "nl", false], // 1.5 vs 1500
      ["Het budget is € 1.500.", "", "Het budget is € 1500.", "nl", false], // undeclared claim: ambiguous
    ];
    for (const [claim, claimLang, passage, passageLang, pass] of cases) {
      expect(numberGuard(claim, claimLang, passage, passageLang) === "", `${claim} over ${passage}`).toBe(pass);
    }
  });

  it("names", () => {
    expect(names("Employees at Acme get the CAO bonus per R-119. Then Payroll pays.")).toEqual([
      "Acme",
      "CAO",
      "R-119",
      "Payroll",
    ]);
  });

  it("the quote path anchors the content", async () => {
    const fee: EvidenceUnit = {
      id: "faq#7",
      documentId: "faq",
      language: "nl",
      text: "Voor thuiswerken geldt een vergoeding van € 25 exclusief btw per maand.",
    };
    const checker = new FakeChecker({ [fee.text]: [0.95, 0.01] });
    const opts: VerifyOptions = { checker, checkerName: "nli", answerLanguage: "nl" };
    let res = await verify('Bij thuiswerk geldt "een vergoeding van € 25 exclusief btw" [eu:faq#7].', [fee], opts);
    expect(res.claims[0]?.verified_by).toBe("quote+model:nli");
    res = await verify('Er geldt "een vergoeding van € 25 inclusief btw" [eu:faq#7].', [fee], opts);
    expect(res.evidence.decision).toBe(Decision.refused);
    res = await verify('Bij thuiswerk geldt "een vergoeding van € 25 exclusief btw" [eu:faq#7].', [fee], { answerLanguage: "nl" });
    expect(res.evidence.decision).toBe(Decision.refused);
  });

  it("admitParaphrase is opt-in", async () => {
    const checker = new FakeChecker({ [leave.text]: [0.97, 0.01] });
    const claim = "Staff get 25 days of annual leave [eu:hr-3#0].";
    const opts: VerifyOptions = { checker, checkerName: "nli", answerLanguage: "en" };
    expect((await verify(claim, [leave], opts)).evidence.decision).toBe(Decision.refused);
    const res = await verify(claim, [leave], { ...opts, admitParaphrase: true });
    expect(res.evidence.decision).toBe(Decision.answered);
    expect(res.claims[0]?.verified_by).toBe("model:nli");
  });

  it("missing facets are named", async () => {
    const opts: VerifyOptions = {
      facets: [
        { id: "notice", label: "the notice period" },
        { id: "leave", label: "annual leave" },
      ],
    };
    const ev = [notice30, leave];
    let res = await verify(
      "The notice period is 30 days [eu:hr-1#0][q:notice]. Employees receive 40 days of annual leave [eu:hr-3#0][q:leave].",
      ev,
      opts,
    );
    expect(res.evidence.decision).toBe(Decision.partial);
    expect(res.evidence.missing_facets).toEqual(["leave"]);
    expect(res.missing_evidence.join("|")).toContain("no verified answer for: annual leave");
    res = await verify(
      "The notice period is 30 days [eu:hr-1#0][q:notice]. Employees receive 25 days of annual leave [eu:hr-3#0][q:leave].",
      ev,
      opts,
    );
    expect(res.evidence.decision).toBe(Decision.answered);
    expect(res.evidence.missing_facets).toBeUndefined();
  });

  it("a clause-final negation is not dropped", async () => {
    const parking: EvidenceUnit = {
      id: "p#1",
      documentId: "p",
      language: "nl",
      text: "De werkgever vergoedt de parkeerkosten niet. Reiskosten worden wel vergoed.",
    };
    // The shared predicate accepts the dropped negation — the hole this closes.
    expect(isSupportedV2("De werkgever vergoedt de parkeerkosten.", parking.text)).toBe(true);
    const sure = new FakeChecker({ [parking.text]: [0.99, 0.0] });
    for (const opts of [{}, { checker: sure, admitParaphrase: true, answerLanguage: "nl" }]) {
      const res = await verify("De werkgever vergoedt de parkeerkosten [eu:p#1].", [parking], opts);
      expect(res.evidence.decision).toBe(Decision.refused);
      expect(res.claims[0]?.reason?.startsWith("negation guard")).toBe(true);
    }
    const res = await verify(
      "De werkgever vergoedt de parkeerkosten niet [eu:p#1]. Reiskosten worden vergoed [eu:p#1].",
      [parking],
    );
    expect(res.evidence.decision).toBe(Decision.answered);
  });

  it("a next-clause negation does not refuse", async () => {
    const ev: EvidenceUnit = {
      id: "c#1",
      documentId: "c",
      language: "nl",
      text: "De werkgever vergoedt de parkeerkosten, maar niet de reiskosten.",
    };
    const res = await verify("De werkgever vergoedt de parkeerkosten [eu:c#1].", [ev]);
    expect(res.evidence.decision).toBe(Decision.answered);
  });

  it("R-119 / R-120: incl. vs excl. btw", async () => {
    const faq: EvidenceUnit = {
      id: "R-119",
      documentId: "hr-faq",
      language: "nl",
      text: "Voor thuiswerken geldt een vergoeding van € 25 exclusief btw per maand.",
      authority: { source_layer: "adopted" },
    };
    const note: EvidenceUnit = {
      id: "R-120",
      documentId: "voorgesteld-beleid",
      language: "nl",
      text: "Voor thuiswerken geldt een vergoeding van € 25 inclusief btw per maand.",
      authority: { source_layer: "proposal" },
    };
    const claim = "Voor thuiswerken geldt een vergoeding van € 25 exclusief btw per maand [eu:R-119].";
    let res = await verify(claim, [faq, note], { answerLanguage: "nl" });
    expect(res.answer).toBe(CONFLICT_REFUSAL_ANSWER);
    expect(res.sources.length).toBe(2);
    expect(res.conflicts[0]?.startsWith("inclusion:")).toBe(true);
    const policy = AuthorityPolicy.ordered(["proposal", "adopted"]).withKey("source_layer");
    res = await verify(claim, [faq, note], { answerLanguage: "nl", authority: policy });
    expect(res.evidence.decision).toBe(Decision.answered);
    expect(res.conflicts[0]).toContain("resolved by authority");
  });

  it("empty leadInFrames disables the content-free rule", async () => {
    const ev: EvidenceUnit[] = [
      { id: "a", documentId: "a", language: "nl", text: "De werknemer heeft recht op 25 vakantiedagen per kalenderjaar." },
    ];
    const answer = "Zo zit het:\n- De werknemer heeft recht op 25 vakantiedagen per kalenderjaar [eu:a]";
    const res = await verify(answer, ev, { answerLanguage: "nl", leadInFrames: [] });
    expect(res.claims.length).toBe(1);
    expect(res.claims[0]?.supported).toBe(false);
    expect(res.claims[0]?.claim.startsWith("Zo zit het")).toBe(true);
  });

  it("an empty actor lexicon switches the role guard off", async () => {
    const ev: EvidenceUnit[] = [{ id: "a", documentId: "a", language: "nl", text: "De werkgever betaalt de rest; je betaalt 4,5%." }];
    const answer = "De werkgever betaalt 4,5% [eu:a].";
    expect((await verify(answer, ev, { answerLanguage: "nl" })).claims[0]?.supported).toBe(false);
    expect((await verify(answer, ev, { answerLanguage: "nl", actors: EMPTY_ACTOR_LEXICON })).claims[0]?.supported).toBe(true);
  });

  it("qualifier pairs are host-extensible", async () => {
    const ev: EvidenceUnit[] = [{ id: "a", documentId: "a", language: "nl", text: "De daluren-toeslag bedraagt 15% tijdens de daluren." }];
    const answer = "The peak-hours supplement is 15% [eu:a].";
    const chk = new FakeChecker({ [(ev[0] as EvidenceUnit).text]: [0.999, 0] });
    const base: VerifyOptions = { answerLanguage: "en", checker: chk, checkerName: "fake" };
    expect((await verify(answer, ev, base)).claims[0]?.supported).toBe(true);
    const withPair: VerifyOptions = {
      ...base,
      qualifierPairs: [...DEFAULT_QUALIFIER_PAIRS, { a: ["peak-hours", "spits"], b: ["daluren", "off-peak"] }],
    };
    expect((await verify(answer, ev, withPair)).claims[0]?.supported).toBe(false);
  });

  it("the exclusion guard has no verdict across languages without a glossary", () => {
    const claim = "Teachers who work from home at least one day a week receive €2.35 per day worked from home.";
    const unit: EvidenceUnit = {
      id: "S1",
      documentId: "thuiswerkregeling Stichting Openbaar Onderwijs Duinrand",
      language: "nl",
      text: "Thuiswerkvergoeding. Medewerkers van het bestuursbureau die op grond van een thuiswerkafspraak ten minste één dag per week thuiswerken, ontvangen een vergoeding van € 2,35 per thuiswerkdag. Voor leraren en onderwijsondersteunend personeel geldt deze vergoeding niet.",
    };
    expect(exclusionGuard(claim, "en", unit, guardConfig())).toBe("");
    const cfg = guardConfig({ gloss: prepareGlossary([["leraren", "teachers"], ["leraar", "teacher"]], null) });
    expect(exclusionGuard(claim, "en", unit, cfg).startsWith("exclusion guard")).toBe(true);
  });

  it("the verb-pair guard has no verdict across languages without a glossary", () => {
    const unit: EvidenceUnit = {
      id: "a",
      documentId: "",
      language: "nl",
      text: "De werknemer vraagt het aanvullend verlof ten minste vier weken van tevoren aan bij de leidinggevende.",
    };
    const claim = "You take the additional leave at least four weeks in advance.";
    expect(verbPairGuard(claim, "en", unit, DEFAULT_VERB_PAIRS, guardConfig())).toBe("");
    const cfg = guardConfig({ gloss: prepareGlossary([["verlof", "leave"], ["aanvullend", "additional"]], null) });
    expect(verbPairGuard(claim, "en", unit, DEFAULT_VERB_PAIRS, cfg).startsWith("verb guard")).toBe(true);
  });

  it("disableDefinitions turns the definition guard off", async () => {
    const ev: EvidenceUnit[] = [
      {
        id: "a",
        documentId: "a",
        language: "nl",
        text: "Een werknemer kan onbetaald verlof (hierna: het Verlof) opnemen. Tijdens het Verlof bouwt de werknemer geen vakantiedagen op.",
      },
    ];
    const answer = "Tijdens verlof bouw je geen vakantiedagen op [eu:a].";
    const chk = new FakeChecker({ [(ev[0] as EvidenceUnit).text]: [0.999, 0] });
    const on: VerifyOptions = { answerLanguage: "nl", admitParaphrase: true, checker: chk, checkerName: "fake" };
    expect((await verify(answer, ev, on)).claims[0]?.supported).toBe(false);
    expect((await verify(answer, ev, { ...on, disableDefinitions: true })).claims[0]?.supported).toBe(true);
  });

  it("parses a glossary TSV", () => {
    const tsv =
      "nl\ten\tpos\tclass\tlemma_nl\tlemma_en\tsep\n" +
      "sluit\tclose\tverb\tverb\tafsluiten\tclose\taf\n" +
      "Controller\tController\tnoun\tparty\tcontroller\tcontroller\t\n" +
      "\tempty\tnoun\tparty\t\t\t\n";
    expect(parseGlossaryTSV(tsv)).toEqual([
      { nl: "sluit", en: "close", lemmaNL: "afsluiten", lemmaEN: "close", sep: "af", class: "verb" },
      { nl: "controller", en: "controller", lemmaNL: "controller", lemmaEN: "controller", sep: "", class: "party" },
    ]);
    expect(() => parseGlossaryTSV("a\tb\nx\ty\n")).toThrow();
  });
});

describe("number forms in running text (golang verify_number_forms_test.go)", () => {
  const nlUnit = (f: string) =>
    "Huur. De maandhuur van de bedrijfsruimte bedraagt " + f + " per maand. De huur wordt jaarlijks geïndexeerd.";
  const nlClaim = (f: string) => "De maandhuur van de bedrijfsruimte bedraagt " + f + " per maand.";
  const enUnit = (f: string) =>
    "Rent. The monthly rent of the business premises is " + f + " per month. The rent is indexed yearly.";
  const enClaim = (f: string) => "The monthly rent of the business premises is " + f + " per month.";
  type Tc = [name: string, unitLang: string, claimLang: string, unit: string, claim: string, refuse: boolean];
  const cases: Tc[] = [];
  for (const f of ["4.000", "4.000,00", "€ 4.000", "€ 4 000", "€4.000,-"]) {
    cases.push(["nl claim " + f, "nl", "nl", nlUnit("€ 4.000"), nlClaim(f), false]);
    cases.push(["nl unit " + f, "nl", "nl", nlUnit(f), nlClaim("€ 4.000"), false]);
  }
  for (const f of ["4,000", "4,000.00", "€ 4,000"]) {
    cases.push(["en claim " + f, "en", "en", enUnit("€ 4,000"), enClaim(f), false]);
    cases.push(["en unit " + f, "en", "en", enUnit(f), enClaim("€ 4,000"), false]);
  }
  for (const sp of [" ", " ", " "]) {
    const cp = sp.codePointAt(0)?.toString(16);
    cases.push([`nl claim € 1 012 (U+${cp})`, "nl", "nl", nlUnit("€ 1.012"), nlClaim("€" + sp + "1" + sp + "012"), false]);
    cases.push([`nl unit € 1 012 (U+${cp})`, "nl", "nl", nlUnit("€" + sp + "1" + sp + "012"), nlClaim("€ 1.012"), false]);
    cases.push([`nl € 1 012 is not 1.021 (U+${cp})`, "nl", "nl", nlUnit("€ 1.021"), nlClaim("€ 1" + sp + "012"), true]);
  }
  cases.push(
    ["nl € 0,23 = 0,23 euro", "nl", "nl", nlUnit("€ 0,23"), nlClaim("0,23 euro"), false],
    ["nl € 0,23 = 23 cent", "nl", "nl", nlUnit("€ 0,23"), nlClaim("23 cent"), false],
    ["en € 0.23 = nl € 0,23", "nl", "en", nlUnit("€ 0,23"), enClaim("€ 0.23"), false],
    ["nl € 0,23 is not € 23", "nl", "nl", nlUnit("€ 0,23"), nlClaim("€ 23"), true],
    ["nl € 0,23 is not € 0,32", "nl", "nl", nlUnit("€ 0,23"), nlClaim("€ 0,32"), true],
    ["en claim writes the dutch amount (ADR-0015)", "nl", "en", nlUnit("€ 4.000"), enClaim("€ 4.000"), true],
    ["en claim writes the dutch amount before euro (ADR-0015)", "nl", "en", nlUnit("€ 4.000"), enClaim("4.000 euro"), true],
    ["nl claim writes the english amount (ADR-0015)", "en", "nl", enUnit("€ 4,000"), nlClaim("€ 4,000"), true],
    ["en claim in english format over the dutch unit", "nl", "en", nlUnit("€ 4.000"), enClaim("€ 4,000"), false],
    ["nl claim in dutch format over the english unit", "en", "nl", enUnit("€ 4,000"), nlClaim("€ 4.000"), false],
    ["4.000 is not 40.000", "nl", "nl", nlUnit("€ 40.000"), nlClaim("€ 4.000"), true],
    ["4.000 is not 4,5", "nl", "nl", nlUnit("€ 4,5"), nlClaim("€ 4.000"), true],
    ["en 4,000 is not 40,000", "en", "en", enUnit("€ 40,000"), enClaim("€ 4,000"), true],
    [
      "4.000 is not the count 4",
      "nl",
      "nl",
      "Parkeren. De huurder krijgt 4 parkeerplaatsen bij de bedrijfsruimte. De huur wordt jaarlijks geïndexeerd.",
      "De huurder krijgt 4.000 parkeerplaatsen bij de bedrijfsruimte.",
      true,
    ],
    [
      "en-declared 4.000 outside money stays ambiguous",
      "nl",
      "en",
      "Personeel. Het bedrijf heeft 4.000 medewerkers in dienst. Zij werken in drie vestigingen.",
      "The company employs 4.000 staff.",
      true,
    ],
  );
  for (const [name, unitLang, claimLang, unit, claim, refuse] of cases) {
    it(name, async () => {
      const res = await verify(claim + " [eu:a]", [{ id: "a", documentId: "d", language: unitLang, text: unit }], {
        answerLanguage: claimLang,
        admitParaphrase: true,
        checker: admitAll,
        checkerName: "admit",
      });
      const got = res.claims[0];
      expect(got?.supported, got?.reason).toBe(!refuse);
    });
  }
});

describe("union reason names a guard only when every pair failed one (golang verify_union_reason_test.go)", () => {
  const evidence: EvidenceUnit[] = [
    { id: "a1", documentId: "a1", language: "nl", text: "Artikel 7:13 BW regelt wanneer de werkgever een bedrag op het loon mag inhouden." },
    { id: "a2", documentId: "a2", language: "nl", text: "Artikel 7:14 BW regelt wanneer de werkgever een bedrag op het loon mag inhouden." },
    { id: "a3", documentId: "a3", language: "nl", text: "Artikel 7:15 BW regelt wanneer de werkgever een bedrag op het loon mag inhouden." },
    { id: "b", documentId: "b", language: "nl", text: "De werkgever mag loon inhouden als de werknemer schade veroorzaakt." },
  ];
  const item = "\n- De werkgever mag loon inhouden als de werknemer schade veroorzaakt [eu:b]";
  const cases: [string, string, boolean][] = [
    ["guard-refused pair first, model-refused pair second", "Volgens artikel 7:13 BW [eu:a2][eu:a1]:", false],
    ["model-refused pair first, guard-refused pair second", "Volgens artikel 7:13 BW [eu:a1][eu:a2]:", false],
    ["every pair guard-refused", "Volgens artikel 7:13 BW [eu:a2][eu:a3]:", true],
  ];
  for (const [name, lead, guard] of cases) {
    it(name, async () => {
      const res = await verify(lead + item, evidence, {
        answerLanguage: "nl",
        admitParaphrase: true,
        checker: lowChecker,
        checkerName: "low",
      });
      const got = res.claims.find((c) => c.claim.includes("schade"))?.reason;
      expect(got).toBeDefined();
      let isGuard = (got as string).includes(" guard");
      if ((got as string).includes("(model:")) isGuard = false;
      expect(isGuard, got).toBe(guard);
    });
  }
});

describe("a party swap binds the value to its word (golang verify_parties_binding_test.go)", () => {
  const oneSentenceNL = "Fietsregeling. De minimumprijs van een fiets is € 500 en de maximumprijs is € 4.000.";
  const oneSentenceEN = "Bike scheme. The minimum price of a bike is € 500 and the maximum price is € 4,000.";
  const twoSentencesNL = "Toeslag. De ondergrens van de toeslag is € 100. De bovengrens van de toeslag is € 300.";
  const twoSentencesEN = "Allowance. The lower limit of the allowance is € 100. The upper limit of the allowance is € 300.";
  const cases: [string, string, string, string, boolean][] = [
    ["nl right word, value after the other word", "nl", oneSentenceNL, "De maximumprijs van een fiets is € 4.000.", false],
    ["nl right word, own clause", "nl", oneSentenceNL, "De minimumprijs van een fiets is € 500.", false],
    ["nl wrong word for 4.000", "nl", oneSentenceNL, "De minimumprijs van een fiets is € 4.000.", true],
    ["nl wrong word for 500", "nl", oneSentenceNL, "De maximumprijs van een fiets is € 500.", true],
    ["en right word", "en", oneSentenceEN, "The maximum price of a bike is € 4,000.", false],
    ["en wrong word", "en", oneSentenceEN, "The minimum price of a bike is € 4,000.", true],
    ["nl two sentences, right word", "nl", twoSentencesNL, "De bovengrens van de toeslag is € 300.", false],
    ["nl two sentences, wrong word", "nl", twoSentencesNL, "De ondergrens van de toeslag is € 300.", true],
    ["en two sentences, right word", "en", twoSentencesEN, "The upper limit of the allowance is € 300.", false],
    ["en two sentences, wrong word", "en", twoSentencesEN, "The lower limit of the allowance is € 300.", true],
  ];
  for (const [name, lang, unit, claim, refuse] of cases) {
    it(name, async () => {
      const res = await verify(claim + " [eu:a]", [{ id: "a", documentId: "d", language: lang, text: unit }], {
        answerLanguage: lang,
        admitParaphrase: true,
        checker: admitAll,
        checkerName: "admit",
      });
      expect(res.claims.length).toBe(1);
      expect(res.claims[0]?.supported, res.claims[0]?.reason).toBe(!refuse);
    });
  }
});

describe("options never move premise selection (golang verify_premise_invariance_test.go)", () => {
  const high = "Veiligheid. De directie beschermt een medewerker die een incident te goeder trouw en naar behoren meldt.";
  class RecordingChecker implements SupportChecker {
    calls: string[] = [];
    check(_claim: string, passage: string): SupportScores {
      this.calls.push(passage);
      return passage === high ? { entailed: 0.75, contradicted: 0.01 } : { entailed: 0.018, contradicted: 0.02 };
    }
  }
  const bestOn = /best entailment ([0-9.]+), contradiction ([0-9.]+) on (\S+?)[;)]/;
  const gloss: [string, string][] = [
    ["directie", "management"], ["beschermt", "protects"], ["medewerker", "employee"],
    ["incident", "incident"], ["goeder", "good"], ["trouw", "faith"], ["meldt", "reports"],
  ];
  const evidence: EvidenceUnit[] = [
    { id: "a", documentId: "d", language: "nl", text: high },
    { id: "b", documentId: "d", language: "nl", text: "Meldingen. Meldingen gaan naar de veiligheidskundige van de directie." },
  ];
  const cases: [string, string][] = [
    ["a guard verdict differs between the modes", "Management protects an employee who reports an incident in good faith [eu:a][eu:b]."],
    ["no guard fires", "Management protects an employee who reports an incident in good faith and properly [eu:a][eu:b]."],
  ];
  for (const [name, claim] of cases) {
    for (const eager of [true, false]) {
      it(`${name}/eager=${String(eager)}`, async () => {
        const calls: string[][] = [];
        const reported: string[] = [];
        const supported: boolean[] = [];
        for (const on of [false, true]) {
          const rec = new RecordingChecker();
          const res = await verifyAnswerInternal(
            claim,
            evidence,
            { answerLanguage: "en", glossary: gloss, conjunctPresence: on, checker: rec, checkerName: "rec" },
            eager,
          );
          calls.push(rec.calls);
          supported.push(res.claims[0]?.supported ?? false);
          const m = bestOn.exec(res.claims[0]?.reason ?? "");
          reported.push(m === null ? "" : `${m[1]}/${m[2]}/${m[3]}`);
        }
        expect(reported[0], "reported premise moved").toBe(reported[1]);
        if (!eager) {
          if (supported[0] !== supported[1]) return;
          calls[0]?.sort();
          calls[1]?.sort();
        }
        expect(calls[0]).toEqual(calls[1]);
      });
    }
  }

  it("lazy scoring matches eager on every vector", async () => {
    const file = loadCase<{ cases: VerifyVector[] }>("verify_answer.json");
    let eagerCalls = 0;
    let lazyCalls = 0;
    for (const c of file.cases) {
      if (Object.keys(c.checker ?? {}).length === 0 && Object.keys(c.checker_claims ?? {}).length === 0) continue;
      const evidence = vectorEvidence(c);
      const run = async (eager: boolean): Promise<[string, number]> => {
        const { opts, checker } = vectorOptions(c, evidence);
        const res = await verifyAnswerInternal(c.answer, evidence, opts, eager);
        return [JSON.stringify(res), checker.calls];
      };
      const [e, en] = await run(true);
      const [l, ln] = await run(false);
      expect(l, `${c.name}: lazy output differs from eager`).toBe(e);
      eagerCalls += en;
      lazyCalls += ln;
    }
    expect(lazyCalls).toBeLessThanOrEqual(eagerCalls);
  });
});

describe("a prepared glossary gives the verdict a fresh preparation gives (golang glossary_bench_test.go)", () => {
  function syntheticGlossary(n: number): GlossaryEntry[] {
    const out: GlossaryEntry[] = [];
    for (let i = 0; out.length < n; i++) {
      const lemma = `woord${i}`;
      for (let k = 0; k < 4 && out.length < n; k++) {
        out.push({ nl: `${lemma}en${k}`, en: `word${i}s${k}`, lemmaNL: lemma, lemmaEN: `word${i}`, class: "noun" });
      }
    }
    out.push({ nl: "verlof", en: "leave", lemmaNL: "verlof", lemmaEN: "leave", class: "other" });
    return out;
  }
  const answer = "You apply for the leave four weeks in advance [eu:a].";
  const ev: EvidenceUnit[] = [
    { id: "a", documentId: "a", language: "nl", text: "De werknemer vraagt het verlof ten minste vier weken van tevoren aan bij de leidinggevende." },
  ];
  const setup = (o: VerifyOptions): VerifyOptions => ({
    ...o,
    answerLanguage: "en",
    admitParaphrase: true,
    checker: new FakeChecker({ [(ev[0] as EvidenceUnit).text]: [0.999, 0] }),
    checkerName: "fake",
  });

  it("concurrent calls share one prepared glossary and the lazy cache", async () => {
    const entries = syntheticGlossary(200);
    const pairs: [string, string][] = [["leidinggevende", "manager"]];
    const prepared: PreparedGlossary = prepareGlossary(pairs, entries);
    const ref = JSON.stringify(await verifyAnswer(answer, ev, setup({ glossaryPrepared: prepared })));
    const runs = Array.from({ length: 16 }, (_, i) =>
      verifyAnswer(answer, ev, setup(i % 2 === 1 ? { glossary: pairs, glossaryEntries: entries } : { glossaryPrepared: prepared })),
    );
    for (const r of await Promise.all(runs)) expect(JSON.stringify(r)).toBe(ref);
  });
});
