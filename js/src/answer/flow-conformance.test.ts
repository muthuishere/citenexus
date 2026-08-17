// Flow-level conformance for the three answer-path signals this port used to
// hardcode (2026-08-17). Each suite reads its expectations from a COMMITTED
// fixture and pins the vector count exactly — a `> 0` floor would let a shrunken
// file pass, which is the hole these suites exist to close.
//
// The fixtures are deliberately the ones that already pin the PRIMITIVES:
//
//   - language.json      → resolveAnswerLanguage (the §11a chain)
//   - tokenize_v2.json   → unsupportedScripts (ADR-0011)
//   - faithful_v2.json   → isSupportedV2 (ADR-0009)
//
// Each primitive shipped in this port with ZERO callers on the answer path, so
// every one of these signals was a constant wearing the primitive's name. These
// suites bind the FLOW to them, which is the thing a caller actually observes;
// binding the predicate alone is what let the 0.10.0 regression through.
//
// The Go twin is golang/answer/flow_conformance_test.go and the Python
// reference is python/tests/answer/test_flow_conformance.py; the three assert
// the same vectors so a divergence is a test failure, not a code review.

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { ask, askWith, type CorpusDoc } from "./answer.js";
import { splitClaims } from "./segment.js";

function fixture<T>(name: string): T {
  const path = fileURLToPath(new URL(`../../../conformance/cases/${name}`, import.meta.url));
  return JSON.parse(readFileSync(path, "utf-8")) as T;
}

const PASSAGE = "The employee shall not disclose confidential information.";

/** Rung 4 of the chain in this port; a committed case that configures anything
 *  else is not reproducible here. Mirrors DEFAULT_ANSWER_LANGUAGE. */
const DEFAULT_ANSWER_LANGUAGE = "en";
const UNDECLARED_LANGUAGE = "und";

// ---------------------------------------------------------------------------
// GAP 1 — the answer language comes from the chain; the evidence languages are
// observed. Both were the literal "en" before.
// ---------------------------------------------------------------------------

interface LanguageVector {
  name: string;
  detection: { is_reliable: boolean } | null;
  answer_language: string | null;
  conversation_language: string | null;
  languages_in_evidence: string[];
  default_answer_language: string;
  expected: string;
}

// The size of conformance/cases/language.json, and how many of those this port's
// flow can EXPRESS. The port has no detector and no conversation state, and its
// rung-4 default is fixed at "en", so a case turning on any of those three is
// not reproducible here — but the reproducible count is pinned too, so the
// subset cannot silently shrink to nothing.
const EXPECTED_LANGUAGE_VECTORS = 6;
const EXPECTED_FLOW_DRIVABLE_LANGUAGE_VECTORS = 4;

/** Whether this port's flow can reproduce the committed case, i.e. whether the
 *  committed `expected` is still the right answer when the only input the flow
 *  accepts is the caller's answer-language request. */
function flowDrivable(v: LanguageVector): boolean {
  if (v.default_answer_language !== DEFAULT_ANSWER_LANGUAGE) return false;
  // Rung 1 wins outright; the rungs below cannot matter.
  if (v.answer_language) return true;
  return v.conversation_language === null && (v.detection === null || !v.detection.is_reliable);
}

describe("flow conformance: the answer language comes from the §11a chain", () => {
  const vectors = fixture<LanguageVector[]>("language.json");

  it("pins the committed vector count", () => {
    expect(vectors).toHaveLength(EXPECTED_LANGUAGE_VECTORS);
  });

  it("pins how many vectors this port's flow can express", () => {
    expect(vectors.filter(flowDrivable)).toHaveLength(EXPECTED_FLOW_DRIVABLE_LANGUAGE_VECTORS);
  });

  for (const v of vectors.filter(flowDrivable)) {
    it(`${v.name}`, async () => {
      const got = await askWith([{ document_id: "doc", text: PASSAGE }], PASSAGE, {
        answerLanguage: v.answer_language ?? undefined,
      });
      // The committed expectation, read from the fixture — never re-derived by
      // calling resolveAnswerLanguage here.
      expect(got.answer_language).toBe(v.expected);
    });
  }
});

describe("flow conformance: evidence languages are observed, not the answer language", () => {
  const vectors = fixture<LanguageVector[]>("language.json");

  it("pins the committed vector count", () => {
    expect(vectors).toHaveLength(EXPECTED_LANGUAGE_VECTORS);
  });

  for (const v of vectors) {
    it(`${v.name}`, async () => {
      // Stamp the committed evidence languages onto real documents. They are an
      // OBSERVATION to report, never an input to the chain — so whatever they
      // are, they must come back out on languages_in_evidence, distinct and in
      // pool order, and they must NOT move answer_language.
      const corpus: CorpusDoc[] = v.languages_in_evidence.map((language, i) => ({
        document_id: String.fromCharCode(97 + i),
        text: PASSAGE,
        language,
      }));
      if (corpus.length === 0) corpus.push({ document_id: "a", text: PASSAGE });

      const got = await askWith(corpus, PASSAGE);
      expect(got.evidence.languages_in_evidence).toEqual([...new Set(v.languages_in_evidence)]);
      // The cited passage reports the DOCUMENT's declared language, or the
      // pinned "und" — never the answer language. This is the assertion that
      // fails if anyone reintroduces the `passageLanguage: answerLanguage`
      // shortcut.
      expect(got.sources).toHaveLength(1);
      expect(got.sources[0]!.passage_language).toBe(
        v.languages_in_evidence[0] ?? UNDECLARED_LANGUAGE,
      );
      // `ask` carries the flow a second time; it must agree field for field.
      expect(ask(corpus, PASSAGE)).toEqual(got);
    });
  }
});

// ---------------------------------------------------------------------------
// GAP 2 — unsupported_scripts is populated from the tokenizer, so "I cannot read
// this script" is distinguishable from "I have no evidence". It was always [].
// ---------------------------------------------------------------------------

interface ScriptVector {
  script: string;
  text: string;
  unsupported_scripts: string[];
}

// The bucket sizes of conformance/cases/tokenize_v2.json.
const EXPECTED_CLAIMED_SCRIPT_VECTORS = 14;
const EXPECTED_UNCLAIMED_SCRIPT_VECTORS = 11;

const scripts = fixture<{ supported: ScriptVector[]; unclaimed: ScriptVector[] }>(
  "tokenize_v2.json",
);

describe("flow conformance: an unreadable question refuses as a CAPABILITY gap", () => {
  it("pins the committed bucket sizes", () => {
    expect(scripts.supported).toHaveLength(EXPECTED_CLAIMED_SCRIPT_VECTORS);
    expect(scripts.unclaimed).toHaveLength(EXPECTED_UNCLAIMED_SCRIPT_VECTORS);
  });

  for (const v of scripts.unclaimed) {
    it(`${v.script}`, async () => {
      const got = await askWith([{ document_id: "doc", text: v.text }], v.text);
      expect(got.evidence.decision).toBe("refused");
      // The committed capability signal, read from the fixture. Before this
      // wiring the flow returned [] here and the caller could not tell an
      // unreadable script from an empty corpus.
      expect(got.evidence.unsupported_scripts).toEqual(v.unsupported_scripts);
      expect(got.missing_evidence[0]).toBe(
        `unsupported script: ${v.unsupported_scripts.join(", ")}`,
      );
    });
  }
});

describe("flow conformance: every CLAIMED script reports no gap", () => {
  for (const v of scripts.supported) {
    it(`${v.script}`, async () => {
      const got = await askWith([{ document_id: "doc", text: v.text }], v.text);
      expect(got.evidence.unsupported_scripts).toEqual(v.unsupported_scripts);
      expect(got.evidence.decision).toBe("answered");
    });
  }
});

// ---------------------------------------------------------------------------
// GAP 3 — verification is per ATOMIC CLAIM with drop-not-fail. The port used to
// gate the whole answer string as one claim, so it passed or refused WHOLE.
// ---------------------------------------------------------------------------

interface FaithfulVector {
  name: string;
  passage: string;
  answer: string;
  supported: boolean;
}

// The bucket sizes of conformance/cases/faithful_v2.json.
const EXPECTED_FAITHFUL_ATTACKS = 9;
const EXPECTED_FAITHFUL_CONTROLS = 30;

const faithful = fixture<{ attacks: FaithfulVector[]; controls: FaithfulVector[] }>(
  "faithful_v2.json",
);

const fixedGenerator = (out: string) => ({ answer: () => out });

describe("flow conformance: drop-not-fail keeps the supported claim", () => {
  it("pins the committed bucket sizes", () => {
    expect(faithful.attacks).toHaveLength(EXPECTED_FAITHFUL_ATTACKS);
    expect(faithful.controls).toHaveLength(EXPECTED_FAITHFUL_CONTROLS);
  });

  // A generation that is one VERBATIM sentence followed by the committed FALSE
  // one must return the verbatim half and drop the lie — with both verdicts
  // recorded. Before this change the port refused BOTH halves, and the caller
  // lost a true, cited sentence to its neighbour.
  for (const v of faithful.attacks) {
    it(`${v.name}`, async () => {
      expect(v.supported).toBe(false);
      const got = await askWith([{ document_id: "doc", text: v.passage }], v.passage, {
        generator: fixedGenerator(`${v.passage} ${v.answer}`),
      });
      expect(got.evidence.decision).toBe("answered");
      expect(got.answer).toBe(v.passage);
      expect(got.evidence.all_claims_verified).toBe(false);
      expect(got.evidence.unsupported_claims_removed).toBe(1);
      expect(got.claims.map((c) => [c.claim, c.supported])).toEqual([
        [v.passage, true],
        [v.answer, false],
      ]);
      // The dropped claim cites nothing: an unsupported claim must never carry
      // an evidence-unit id, or a caller could follow the citation and find the
      // lie "sourced".
      expect(got.claims[1]!.sources).toEqual([]);
    });
  }
});

describe("flow conformance: no surviving claim is the GATE's refusal", () => {
  for (const v of faithful.attacks) {
    it(`${v.name}`, async () => {
      const got = await askWith([{ document_id: "doc", text: v.passage }], v.passage, {
        generator: fixedGenerator(v.answer),
      });
      expect(got.evidence.decision).toBe("refused");
      expect(got.missing_evidence[0]).toBe("generated answer failed the faithfulness gate");
    });
  }
});

describe("flow conformance: every control answers whole", () => {
  for (const v of faithful.controls) {
    it(`${v.name}`, async () => {
      expect(v.supported).toBe(true);
      const got = await askWith([{ document_id: "doc", text: v.passage }], v.passage, {
        generator: fixedGenerator(v.answer),
      });
      expect(got.evidence.decision).toBe("answered");
      expect(got.evidence.all_claims_verified).toBe(true);
      expect(got.evidence.unsupported_claims_removed).toBe(0);
      expect(got.answer).toBe(splitClaims(v.answer).join(" "));
    });
  }
});
