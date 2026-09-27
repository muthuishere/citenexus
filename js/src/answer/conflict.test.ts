// The ADR-0007 conflict vectors, asserted as a BINDING contract.
//
// `conformance/cases/conflict.json` is the cross-port contract for conflict
// surfacing (ADR-0010 tier 1: native in Python, Go and JS, byte-identical).
// This mirrors `python/tests/answer/test_conflict_conformance.py` case for
// case: same buckets, same pinned counts, verdict AND rule name, plus the
// argument-order symmetry check. A port that only reproduces one argument order
// has not reproduced the contract — post-fusion candidates are compared in an
// arbitrary order.

import { describe, expect, it } from "vitest";

import { loadCase } from "../conform/fixtures.js";
import {
  CONFLICT_TOP_K,
  collapseNearDuplicates,
  describeConflicts,
  detectConflict,
  findConflicts,
  fold,
  isNearDuplicate,
} from "./conflict.js";
import { readNumber } from "./numbers.js";

interface PairCase {
  domain?: string;
  label?: string;
  left: string;
  right: string;
  conflict: boolean;
  rule: string | null;
  /** ADR-0015 buckets only; absent or null = undeclared. */
  left_language?: string | null;
  right_language?: string | null;
}

interface NumberReadingCase {
  raw: string;
  dash: boolean;
  language: string | null;
  key: string;
}

interface DuplicateCase {
  label: string;
  left: string;
  right: string;
  collapses: boolean;
}

const VECTORS = loadCase<{
  true_conflicts: PairCase[];
  hard_negatives: PairCase[];
  unrelated: PairCase[];
  heldout_conflicts: PairCase[];
  heldout_negatives: PairCase[];
  non_latin: PairCase[];
  near_duplicates: DuplicateCase[];
  identifier_tokenization: PairCase[];
  inclusion: PairCase[];
  number_formats: PairCase[];
  number_readings: NumberReadingCase[];
}>("conflict.json");

/** Bucket sizes, pinned. A vector silently dropped from a bucket is a weakened
 *  contract that no per-case assertion can see. */
const EXPECTED_COUNTS: Record<string, number> = {
  true_conflicts: 38, // 27 en + 11 nl
  hard_negatives: 39, // 27 en + 12 nl
  unrelated: 27, // 22 en + 5 nl
  heldout_conflicts: 5,
  heldout_negatives: 10,
  non_latin: 30,
  near_duplicates: 9,
  identifier_tokenization: 2,
  // ADR-0015
  inclusion: 19,
  number_formats: 14,
  number_readings: 46,
};

const PAIR_BUCKETS = [
  "true_conflicts",
  "hard_negatives",
  "unrelated",
  "heldout_conflicts",
  "heldout_negatives",
  // ADR-0011. Every non-Latin vector in this bucket scored "no conflict"
  // while conflict ran on the frozen, ASCII-only v1 tokenizer.
  "non_latin",
  // ADR-0015. These carry left_language / right_language; the others omit
  // them, which reads as undeclared.
  "inclusion",
  "number_formats",
] as const;

describe("conflict.json bucket shape", () => {
  it("bucket names and sizes are pinned", () => {
    const sizes = Object.fromEntries(
      Object.entries(VECTORS).map(([k, v]) => [k, (v as unknown[]).length]),
    );
    expect(sizes).toEqual(EXPECTED_COUNTS);
    expect(Object.values(EXPECTED_COUNTS).reduce((a, b) => a + b, 0)).toBe(239);
  });
});

for (const bucket of PAIR_BUCKETS) {
  describe(`detectConflict — ${bucket}`, () => {
    VECTORS[bucket].forEach((c, i) => {
      it(`${bucket}-${i} ${c.domain ?? ""}/${c.label ?? ""}`, () => {
        const finding = detectConflict(c.left, c.right, {
          leftLanguage: c.left_language ?? null,
          rightLanguage: c.right_language ?? null,
        });
        expect(
          finding !== null,
          `expected conflict=${c.conflict}\n  left:  ${c.left}\n  right: ${c.right}\n  got:   ${JSON.stringify(finding)}`,
        ).toBe(c.conflict);
        expect(finding ? finding.rule : null).toBe(c.rule);
      });
    });
  });
}

describe("isNearDuplicate — near_duplicates", () => {
  VECTORS.near_duplicates.forEach((c, i) => {
    it(`near_duplicates-${i} ${c.label}`, () => {
      expect(
        isNearDuplicate(c.left, c.right) !== null,
        `expected collapses=${c.collapses}\n  left:  ${c.left}\n  right: ${c.right}`,
      ).toBe(c.collapses);
    });
  });
});

describe("detectConflict — identifier_tokenization", () => {
  // A letter-leading token containing digits ("p50") is an identifier, not a
  // measured value. Getting this backwards produced the spike's only false
  // conflict.
  VECTORS.identifier_tokenization.forEach((c, i) => {
    it(`identifier_tokenization-${i}`, () => {
      expect(detectConflict(c.left, c.right) !== null).toBe(c.conflict);
    });
  });
});

describe("detection is symmetric", () => {
  it("every pairwise vector holds with the arguments swapped", () => {
    for (const bucket of PAIR_BUCKETS) {
      for (const c of VECTORS[bucket]) {
        const swapped = detectConflict(c.right, c.left, {
          leftLanguage: c.right_language ?? null,
          rightLanguage: c.left_language ?? null,
        });
        expect(
          swapped !== null,
          `${bucket}/${c.label ?? ""}: asymmetric verdict\n  left:  ${c.left}\n  right: ${c.right}`,
        ).toBe(c.conflict);
      }
    }
  });
});

describe("readNumber — number_readings", () => {
  // ADR-0015: every port reads a number to the same comparison key.
  VECTORS.number_readings.forEach((c, i) => {
    it(`number_readings-${i} ${c.raw}${c.dash ? ",-" : ""} [${c.language ?? "undeclared"}]`, () => {
      expect(readNumber(c.raw, { dash: c.dash, language: c.language }).key).toBe(c.key);
    });
  });
});

// ── the small surface around the predicate ─────────────────────────────────

describe("fold", () => {
  it("folds one trailing s on a long enough token", () => {
    expect(fold("requires")).toBe("require");
    expect(fold("attracts")).toBe("attract");
  });

  it("never folds after s / u / i, and never a short token", () => {
    expect(fold("class")).toBe("class");
    expect(fold("status")).toBe("status");
    expect(fold("analysis")).toBe("analysis");
    expect(fold("gas")).toBe("gas");
    expect(fold("is")).toBe("is");
  });

  it("is not a stemmer", () => {
    expect(fold("policy")).toBe("policy");
    expect(fold("does")).toBe("doe"); // which is why the raw token is what the
    // stopword and negation tables are matched against.
  });
});

describe("findConflicts", () => {
  it("reports positions within the window, never a winner", () => {
    const pairs = findConflicts([
      "The dividend for the period was 12 cents per share.",
      "The unrelated purge policy requires a 30 second hold.",
      "The dividend for the period was 30 cents per share.",
    ]);
    expect(pairs).toHaveLength(1);
    expect(pairs[0]!.left).toBe(0);
    expect(pairs[0]!.right).toBe(2);
    expect(pairs[0]!.finding.rule).toBe("value");
  });

  it("compares only the first CONFLICT_TOP_K passages", () => {
    expect(CONFLICT_TOP_K).toBe(6);
    const filler = [
      "The reactor purge policy requires a hold.",
      "Archived correspondence is retained offsite.",
      "Delivery windows are agreed in writing.",
      "The auditor reviews inventory counts quarterly.",
      "Access badges expire on termination.",
      "Training records are stored by the registrar.",
    ];
    const passages = [
      "The liability cap is 5 million.",
      ...filler,
      "The liability cap is 2 million.",
    ];
    expect(findConflicts(passages)).toHaveLength(0);
    expect(findConflicts(passages, passages.length)).toHaveLength(1);
  });
});

describe("describeConflicts", () => {
  it("names both documents and neither as the winner", () => {
    const passages = [
      "The employee shall disclose confidential information to third parties.",
      "The employee shall not disclose confidential information to third parties.",
    ];
    const pairs = findConflicts(passages);
    expect(describeConflicts(pairs, ["policy-a", "policy-b"])).toEqual([
      "negation: policy-a vs policy-b (0 vs 1 negations)",
    ]);
  });
});

describe("collapseNearDuplicates", () => {
  it("keeps the first of a clone set and every non-clone", () => {
    const clone = "The vendor shall notify the customer within 30 days of a breach.";
    expect(
      collapseNearDuplicates([clone, clone, "The reactor purge policy requires a 30 second hold."]),
    ).toEqual([0, 2]);
  });

  it("never collapses a contradiction into a corroboration", () => {
    const passages = [
      "The employee shall disclose confidential information to third parties.",
      "The employee shall not disclose confidential information to third parties.",
    ];
    expect(collapseNearDuplicates(passages)).toEqual([0, 1]);
  });
});
