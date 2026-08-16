// Tests for the model seam and the write-path vector guard. These import only
// the pure module, never `ingest.ts`, so they run with NO native library built —
// the guarantee "a degenerate vector never becomes a row" is provable offline.

import { describe, it, expect, expectTypeOf } from "vitest";

import { checkVector, isZeroVector, type Embedder } from "./embedder.js";

describe("the Embedder seam (ADR-0014 R2)", () => {
  it("accepts an ASYNC embedder — the shape every real provider has", () => {
    // Before this change the type was `(text: string) => number[]`, and tsc
    // rejected exactly this assignment with TS2322, so no network- or
    // model-backed embedder could be injected at all.
    const httpEmbedder: Embedder = async (text: string) => [text.length, 1];
    expectTypeOf(httpEmbedder).toMatchTypeOf<Embedder>();
  });

  it("still accepts a synchronous embedder — the hermetic fakes", () => {
    const fake: Embedder = (text: string) => [text.length, 1];
    expectTypeOf(fake).toMatchTypeOf<Embedder>();
  });

  it("lets a failing embedder REJECT instead of returning a placeholder", async () => {
    const failing: Embedder = () => Promise.reject(new Error("model call timed out after 30s"));
    await expect(failing("x")).rejects.toThrow(/timed out/);
  });
});

describe("write-path vector guard", () => {
  // The regression this whole change exists for: with the old seam a timed-out
  // model returned a zero vector, ingest indexed it, and the row scored 0.0000
  // against every query with no error and no flag — indistinguishable from a
  // document that genuinely embeds far away.
  it("rejects the zero vector", () => {
    expect(() => checkVector("doc::0::1", [0, 0, 0, 0], 4)).toThrow(/zero vector/);
  });

  it("rejects an empty or non-array vector", () => {
    expect(() => checkVector("eu", [], 0)).toThrow(/empty vector/);
    expect(() => checkVector("eu", undefined, 0)).toThrow(/non-vector/);
    expect(() => checkVector("eu", "[0.1]", 0)).toThrow(/non-vector/);
    expect(() => checkVector("eu", [0.1, "x"], 0)).toThrow(/non-vector/);
  });

  it("rejects a wrong-dimension vector", () => {
    expect(() => checkVector("eu", [1, 2], 4)).toThrow(/2-dim vector/);
  });

  it("rejects NaN / Infinity", () => {
    expect(() => checkVector("eu", [1, NaN], 0)).toThrow(/non-finite/);
    expect(() => checkVector("eu", [1, Infinity], 0)).toThrow(/non-finite/);
  });

  it("accepts a real vector, and the first one defines the run's dimension", () => {
    expect(checkVector("eu", [0, 0, 0.5, 0], 0)).toEqual([0, 0, 0.5, 0]);
    expect(checkVector("eu", [0, 0, 0.5, 0], 4)).toEqual([0, 0, 0.5, 0]);
  });

  it("isZeroVector matches the Python reference", () => {
    expect(isZeroVector([0, 0, 0])).toBe(true);
    expect(isZeroVector([])).toBe(true);
    expect(isZeroVector([0, -0])).toBe(true);
    expect(isZeroVector([0, 1e-12])).toBe(false);
    expect(isZeroVector([-1, 0])).toBe(false);
  });
});
