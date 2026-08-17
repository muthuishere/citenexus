// `conformance/cases/vector_validation.json`, asserted as a BINDING contract.
//
// The cross-port definition of A VALID EMBEDDING BATCH (ADR-0010 tier 1:
// structural/arithmetic, so implemented NATIVELY in each port — no Rust, no
// native library, plain ESM unaffected). It exists because the three ports did
// not agree: Python validated NOTHING (a provider returning fewer vectors than
// texts shifted every text→vector pairing and silently corrupted the index), Go
// rejected empty/dimension/all-zero, and JS rejected those PLUS non-finite — so
// two ports pinned "byte-for-byte identical" disagreed about what a valid vector
// even is.
//
// This mirrors `python/tests/conformance/test_vector_validation_vectors.py` and
// `golang/contracts/vector_validation_test.go` case for case: same buckets, same
// EXACT pinned counts, verdict AND rejection reason, plus the pinned rejection
// order. The JSON is read as OPAQUE DATA — nothing here re-derives an
// expectation by calling the code under test, which is how this class of bug
// survived in the first place.

import { describe, expect, it } from "vitest";

import { loadCase } from "./conform/fixtures.js";
import { checkVector, embedTexts, type EmbeddingProvider } from "./contracts.js";

interface VectorCase {
  name: string;
  /** Numbers, or one of the pinned tokens "NaN" / "Infinity" / "-Infinity". */
  vector: (number | string)[];
  dim: number;
  valid: boolean;
  reason: string | null;
}

interface NonVectorCase {
  name: string;
  vector: unknown;
  dim: number;
  valid: boolean;
  reason: string;
}

interface ArityCase {
  name: string;
  texts: number;
  vectors: number;
  valid: boolean;
  reason: string | null;
}

const VECTORS = loadCase<{
  reason_order: string[];
  non_finite_tokens: string[];
  check_vector: VectorCase[];
  non_vector: NonVectorCase[];
  batch_arity: ArityCase[];
}>("vector_validation.json");

/** Case counts, pinned EXACTLY. A floor (`> 0`) lets a shrunken file pass
 *  silently — every bucket is a distinct failure mode, and one silently dropped
 *  is a weakened contract that no per-case assertion can see. */
const EXPECTED_COUNTS: Record<string, number> = {
  check_vector: 29,
  non_vector: 10,
  batch_arity: 9,
};

const NON_FINITE: Record<string, number> = {
  NaN: Number.NaN,
  Infinity: Number.POSITIVE_INFINITY,
  "-Infinity": Number.NEGATIVE_INFINITY,
};

/** Decode one fixture component — a number, or a pinned non-finite token. */
function decode(component: number | string): number {
  if (typeof component === "string") {
    const value = NON_FINITE[component];
    if (value === undefined) throw new Error(`unknown non-finite token ${component}`);
    return value;
  }
  return component;
}

/** Map a thrown error back to the contract's rejection vocabulary, by reading
 *  THE MESSAGE THE PORT PRODUCES. A port whose message does not name the rule it
 *  applied cannot be held to the rejection ORDER, which is half of this
 *  contract. */
function classify(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err);
  if (message.includes("non-vector")) return "non_vector";
  if (message.includes("empty vector")) return "empty";
  if (message.includes("-dim vector")) return "dimension";
  if (message.includes("non-finite")) return "non_finite";
  if (message.includes("zero vector")) return "zero";
  if (message.includes("vectors for")) return "cardinality";
  throw new Error(`error message names no rejection rule: ${message}`);
}

function capture(fn: () => unknown): unknown {
  try {
    fn();
  } catch (err) {
    return err;
  }
  return undefined;
}

describe("vector_validation.json bucket shape", () => {
  it("carries exactly the pinned buckets and nothing else", () => {
    expect(Object.keys(VECTORS).sort()).toEqual(
      ["batch_arity", "check_vector", "non_finite_tokens", "non_vector", "reason_order"].sort(),
    );
  });

  it("pins every bucket size EXACTLY", () => {
    for (const [bucket, want] of Object.entries(EXPECTED_COUNTS)) {
      expect(VECTORS[bucket as keyof typeof VECTORS]).toHaveLength(want);
    }
    expect(Object.values(EXPECTED_COUNTS).reduce((a, b) => a + b, 0)).toBe(48);
  });

  it("has unique case names within each bucket", () => {
    for (const bucket of Object.keys(EXPECTED_COUNTS)) {
      const names = (VECTORS[bucket as "check_vector"] as { name: string }[]).map((c) => c.name);
      expect(new Set(names).size).toBe(names.length);
    }
  });

  it("pins the rejection ORDER — part of the contract, not incidental", () => {
    expect(VECTORS.reason_order).toEqual([
      "non_vector",
      "empty",
      "dimension",
      "non_finite",
      "zero",
    ]);
    expect(VECTORS.non_finite_tokens).toEqual(["NaN", "Infinity", "-Infinity"]);
  });

  it("exercises every rejection rule — coverage asserted, not hoped for", () => {
    const reasons = new Set(
      VECTORS.check_vector.filter((c) => !c.valid).map((c) => c.reason),
    );
    expect([...reasons].sort()).toEqual(["dimension", "empty", "non_finite", "zero"]);
    expect(VECTORS.check_vector.some((c) => c.valid)).toBe(true);
    expect(VECTORS.batch_arity.some((c) => c.valid)).toBe(true);
    expect(VECTORS.batch_arity.some((c) => !c.valid)).toBe(true);
  });
});

describe("checkVector — verdict and rejection reason for every vector", () => {
  for (const c of VECTORS.check_vector) {
    it(c.name, () => {
      const vector = c.vector.map(decode);
      if (c.valid) {
        expect(c.reason).toBeNull();
        expect(checkVector(c.name, vector, c.dim)).toEqual(vector);
        return;
      }
      const err = capture(() => checkVector(c.name, vector, c.dim));
      expect(err, `checkVector accepted ${c.name}, contract rejects it`).toBeInstanceOf(Error);
      expect(classify(err)).toBe(c.reason);
      // The rejection must name the offending unit, never just the run: a
      // corpus-wide "bad vector" tells an operator nothing about which EU to fix.
      expect((err as Error).message).toContain(c.name);
    });
  }
});

describe("checkVector — payloads that are not numeric arrays at all", () => {
  // Go needs no equivalent: []float64 makes these unrepresentable, which is a
  // STRONGER guarantee than a runtime TypeError. Python and JS both take an
  // untyped payload from a provider and must refuse it.
  for (const c of VECTORS.non_vector) {
    it(c.name, () => {
      expect(c.valid).toBe(false);
      expect(c.reason).toBe("non_vector");
      const err = capture(() => checkVector(c.name, c.vector, c.dim));
      expect(err).toBeInstanceOf(TypeError);
      expect(classify(err)).toBe("non_vector");
    });
  }
});

/** A provider that returns a fixed number of vectors regardless of how many
 *  texts it was given — success reported, contract broken. */
function arityProvider(count: number): EmbeddingProvider {
  return {
    embed: () => Array.from({ length: count }, () => [1.0, 2.0]),
  };
}

describe("embedTexts — one vector per input text, in input order", () => {
  // The rule Python missed entirely, and the most damaging of the five: it is
  // the only one whose failure leaves the index PLAUSIBLY wrong, with every
  // downstream signal (row count, scores, citation coverage) still healthy.
  for (const c of VECTORS.batch_arity) {
    it(c.name, async () => {
      const texts = Array.from({ length: c.texts }, (_, i) => `text-${i}`);
      if (c.valid) {
        expect(c.reason).toBeNull();
        await expect(embedTexts(arityProvider(c.vectors), texts)).resolves.toHaveLength(c.texts);
        return;
      }
      let err: unknown;
      try {
        await embedTexts(arityProvider(c.vectors), texts);
      } catch (caught) {
        err = caught;
      }
      expect(err, `embedTexts accepted ${c.vectors} vectors for ${c.texts} texts`).toBeInstanceOf(
        Error,
      );
      expect(classify(err)).toBe(c.reason);
      // Both counts must appear, so the operator sees the SHAPE of the mismatch
      // rather than only that there was one.
      expect((err as Error).message).toContain(String(c.texts));
      expect((err as Error).message).toContain(String(c.vectors));
    });
  }
});
