import { readFileSync } from "node:fs";

import { describe, expect, expectTypeOf, it } from "vitest";

import {
  embedOne,
  embedTexts,
  isEmbeddingProvider,
  NotAnEmbedderError,
  type Awaitable,
  type EmbeddingProvider,
  type GeneratorProvider,
  type SingleTextEmbedder,
  type Vector,
} from "./contracts.js";
import * as root from "./index.js";

// ---------------------------------------------------------------------------
// Providers written the way an outsider would write them: object literals and
// plain classes that extend nothing of ours.
// ---------------------------------------------------------------------------

const syncEmbedder = {
  calls: [] as (readonly string[])[],
  embed(texts: readonly string[]): Vector[] {
    this.calls.push([...texts]);
    return texts.map((t) => [t.length, 1, 0]);
  },
};

const asyncEmbedder = {
  calls: [] as (readonly string[])[],
  async embed(texts: readonly string[]): Promise<Vector[]> {
    this.calls.push([...texts]);
    return texts.map((t) => [t.length, 1, 0]);
  },
};

const singleText: SingleTextEmbedder = (text: string) => [text.length, 1, 0];

class OutsideGenerator {
  seen: string[] = [];
  async answer(question: string, passage: string, answerLanguage = "en"): Promise<string> {
    this.seen.push(`${question}|${answerLanguage}`);
    return passage;
  }
}

describe("the published contracts (ADR-0014 R4)", () => {
  it("re-exports both contracts and their helpers from the package root", () => {
    expect(typeof root.embedTexts).toBe("function");
    expect(typeof root.embedOne).toBe("function");
    expect(typeof root.isEmbeddingProvider).toBe("function");
    expect(typeof root.singleFrom).toBe("function");
    expect(root.NotAnEmbedderError).toBe(NotAnEmbedderError);
  });

  it("is satisfied by shape alone — nothing extends a CiteNexus class", () => {
    expectTypeOf(syncEmbedder).toMatchTypeOf<EmbeddingProvider>();
    expectTypeOf(asyncEmbedder).toMatchTypeOf<EmbeddingProvider>();
    expectTypeOf(new OutsideGenerator()).toMatchTypeOf<GeneratorProvider>();
    expect(Object.getPrototypeOf(syncEmbedder)).toBe(Object.prototype);
  });

  it("accepts a synchronous AND an asynchronous provider (Awaitable<T>)", () => {
    // The strict `=> Promise<T>` spelling would lock the hermetic fakes — the
    // reference implementations of these very contracts — out of the contract.
    expectTypeOf<Awaitable<string>>().toEqualTypeOf<string | Promise<string>>();
    const sync: EmbeddingProvider = { embed: (t) => t.map(() => [1]) };
    const async_: EmbeddingProvider = { embed: async (t) => t.map(() => [1]) };
    expect(isEmbeddingProvider(sync) && isEmbeddingProvider(async_)).toBe(true);
  });

  it("publishes NO contract for the seams this port cannot consume", () => {
    // Completion, vision and reranking have no call site anywhere in the JS
    // port — `grep -i rerank js/src` is empty, and there is no Candidate type
    // a rerank contract could even be spelled in terms of. A contract nothing
    // consumes advertises support that does not exist. See design.md §1.
    const source = readFileSync(new URL("./contracts.ts", import.meta.url), "utf8");
    for (const absent of [
      "CompletionProvider",
      "VisionProvider",
      "RerankerProvider",
      "Candidate",
      "complete(",
      "describe(",
      "rerank(",
    ]) {
      expect(source).not.toContain(absent);
    }
  });

  it("names no transport concern in any contract method (R3)", () => {
    const source = readFileSync(new URL("./contracts.ts", import.meta.url), "utf8");
    const interfaces = source.slice(source.indexOf("export interface"));
    for (const banned of ["base_url", "baseUrl", "headers", "transport", "timeout", "apiKey"]) {
      expect(interfaces).not.toContain(`${banned}:`);
    }
  });
});

// ---------------------------------------------------------------------------
// The Python naming hazard, checked rather than assumed
// ---------------------------------------------------------------------------

describe("the single-text and batch shapes cannot be confused", () => {
  // Python had to name the batch method `embed_many` because `str` IS a
  // `Sequence[str]`. In TS the two seams are not even the same KIND of value:
  // the single-text seam is a FUNCTION, the batch contract is an OBJECT with an
  // `embed` method — so `typeof` discriminates them with certainty and the
  // natural name `embed` is safe.
  it("the type guard tells them apart", () => {
    expect(isEmbeddingProvider(syncEmbedder)).toBe(true);
    expect(isEmbeddingProvider(asyncEmbedder)).toBe(true);
    expect(isEmbeddingProvider(singleText)).toBe(false);
    expect(isEmbeddingProvider(null)).toBe(false);
    expect(isEmbeddingProvider(undefined)).toBe(false);
    expect(isEmbeddingProvider({})).toBe(false);
    expect(isEmbeddingProvider({ embed: 3 })).toBe(false);
    expect(isEmbeddingProvider("embed")).toBe(false);
  });

  it("a string is not assignable where a batch of texts is required", () => {
    expectTypeOf<string>().not.toMatchTypeOf<readonly string[]>();
  });
});

// ---------------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------------

describe("embedTexts — the one place the port decides how to talk to an embedder", () => {
  it("prefers the batch contract and preserves input order", async () => {
    const provider = {
      batches: [] as string[][],
      embed(texts: readonly string[]): Vector[] {
        this.batches.push([...texts]);
        return texts.map((t) => [t.length]);
      },
    };
    const vecs = await embedTexts(provider, ["a", "bb", "ccc"]);
    expect(provider.batches).toEqual([["a", "bb", "ccc"]]);
    expect(vecs).toEqual([[1], [2], [3]]);
  });

  it("falls back to the deprecated single-text shape, per text, in order", async () => {
    const seen: string[] = [];
    const single: SingleTextEmbedder = (text) => {
      seen.push(text);
      return [text.length];
    };
    expect(await embedTexts(single, ["a", "bb"])).toEqual([[1], [2]]);
    expect(seen).toEqual(["a", "bb"]);
  });

  it("calls no model at all for an empty input", async () => {
    const provider = { batches: 0, embed(t: readonly string[]) { this.batches++; return t.map(() => [1]); } };
    expect(await embedTexts(provider, [])).toEqual([]);
    expect(provider.batches).toBe(0);
  });

  it("propagates a provider rejection unchanged — never a placeholder vector", async () => {
    const failing: EmbeddingProvider = {
      embed: () => Promise.reject(new Error("model call timed out after 30s")),
    };
    await expect(embedTexts(failing, ["a"])).rejects.toThrow(/timed out/);

    const failingSingle: SingleTextEmbedder = () => Promise.reject(new Error("timed out"));
    await expect(embedTexts(failingSingle, ["a"])).rejects.toThrow(/timed out/);
  });

  it("refuses a value that is neither shape, loudly", async () => {
    await expect(embedTexts({} as never, ["a"])).rejects.toThrow(NotAnEmbedderError);
    await expect(embedTexts(null as never, ["a"])).rejects.toThrow(NotAnEmbedderError);
  });

  it("refuses a batch whose length does not match the input", async () => {
    const short: EmbeddingProvider = { embed: () => [[1]] };
    await expect(embedTexts(short, ["a", "b"])).rejects.toThrow(/1 vectors for 2 texts/);
  });

  it("embedOne is a batch of one", async () => {
    const provider = {
      batches: [] as string[][],
      embed(texts: readonly string[]): Vector[] {
        this.batches.push([...texts]);
        return texts.map((t) => [t.length]);
      },
    };
    expect(await embedOne(provider, "hello")).toEqual([5]);
    expect(provider.batches).toEqual([["hello"]]);
  });
});

describe("singleFrom — a batch provider plugs into the single-text ingest seam", () => {
  it("adapts without the author writing glue", async () => {
    const adapted = root.singleFrom(syncEmbedder);
    expect(await adapted("hello")).toEqual([5, 1, 0]);
  });

  it("reports a short batch rather than returning a placeholder", async () => {
    await expect(root.singleFrom({ embed: () => [] })("hello")).rejects.toThrow();
  });
});
