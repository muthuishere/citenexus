// The proof: a provider written OUTSIDE CiteNexus drives the JS port.
//
// Everything in this file is deliberately written the way a third party would
// write it, and the constraints are ASSERTED rather than assumed:
//
//   - the provider classes import ONLY the published contract types — no fakes,
//     no models, no concrete CiteNexus class;
//   - they extend nothing (asserted on the prototype chain);
//   - they open no socket (asserted by replacing `globalThis.fetch` with a
//     detonator for the duration of the end-to-end run).
//
// It is the JS twin of python/tests/test_third_party_provider.py. If it passes,
// the contract is usable by someone who has only read the published interface.
// Without it, "there is a contract" is a claim.

import { readFileSync } from "node:fs";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { askWith, type AskProviders, type CorpusDoc } from "./answer/answer.js";
import type { EmbeddingProvider, GeneratorProvider, Vector } from "./contracts.js";
import { Decision } from "./result/result.js";

// ---------------------------------------------------------------------------
// The third-party provider suite. Nothing below names a CiteNexus class.
// ---------------------------------------------------------------------------

const WORD = /[\p{L}\p{N}_]+/gu;

function words(text: string): string[] {
  return text.toLowerCase().match(WORD) ?? [];
}

/** A hashing vectorizer that never leaves the process. Satisfies
 *  `EmbeddingProvider` by shape alone: one batch method, because a batch is the
 *  primitive and a single text is a batch of one. */
class InProcessEmbedding implements EmbeddingProvider {
  readonly batchSizes: number[] = [];
  constructor(private readonly dim = 96) {}

  embed(texts: readonly string[]): Vector[] {
    this.batchSizes.push(texts.length);
    return texts.map((t) => this.one(t));
  }

  private one(text: string): Vector {
    const vec = new Array<number>(this.dim).fill(0);
    for (const word of words(text)) {
      let h = 2166136261;
      for (let i = 0; i < word.length; i++) {
        h = Math.imul(h ^ word.charCodeAt(i), 16777619) >>> 0;
      }
      const idx = h % this.dim;
      vec[idx] = (vec[idx] ?? 0) + 1;
    }
    const norm = Math.sqrt(vec.reduce((acc, v) => acc + v * v, 0));
    if (norm === 0) {
      // The contract says: never hand back a placeholder. A text this model
      // cannot represent is a failure, not a zero vector.
      throw new Error("in-process embedding: nothing to embed");
    }
    return vec.map((v) => v / norm);
  }
}

/** An EXTRACTIVE model: it quotes the passage, so it cannot hallucinate. It
 *  returns the sentence with the most overlap with the question, VERBATIM —
 *  which is exactly what CiteNexus's faithfulness gate demands of any generator,
 *  and the reason an extractive model is the best one. */
class InProcessGenerator implements GeneratorProvider {
  readonly questions: string[] = [];
  readonly languages: (string | undefined)[] = [];

  answer(question: string, passage: string, answerLanguage?: string): string {
    this.questions.push(question);
    this.languages.push(answerLanguage);
    const wanted = new Set(words(question));
    const sentences = passage
      .split(/(?<=[.!?])\s+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (sentences.length === 0) throw new Error("in-process generator: nothing to quote");
    let best = sentences[0]!;
    let bestScore = -1;
    for (const s of sentences) {
      const score = words(s).filter((w) => wanted.has(w)).length;
      if (score > bestScore) {
        best = s;
        bestScore = score;
      }
    }
    return best;
  }
}

// ---------------------------------------------------------------------------
// The corpus
// ---------------------------------------------------------------------------

const NDA =
  "The employee shall not disclose confidential information to any third party. " +
  "This obligation survives termination of employment for a period of five years.";
const LEASE =
  "The tenant shall give the landlord at least thirty days written notice " +
  "before terminating a month to month tenancy.";

const corpus: CorpusDoc[] = [
  { document_id: "nda", text: NDA },
  { document_id: "lease", text: LEASE },
];

function providers(): {
  embedding: InProcessEmbedding;
  generator: InProcessGenerator;
  set: AskProviders;
} {
  const embedding = new InProcessEmbedding();
  const generator = new InProcessGenerator();
  return { embedding, generator, set: { embedding, generator } };
}

// ---------------------------------------------------------------------------
// No network, for the duration of every end-to-end run
// ---------------------------------------------------------------------------

const realFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = (() => {
    throw new Error("a third-party in-process provider must not open a socket");
  }) as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
});

// ---------------------------------------------------------------------------
// 1. The providers satisfy the published contracts, owning nothing of ours
// ---------------------------------------------------------------------------

describe("a third-party provider satisfies the contract without inheriting it", () => {
  it("extends no CiteNexus class", () => {
    for (const provider of [new InProcessEmbedding(), new InProcessGenerator()]) {
      // The prototype chain is exactly [own class, Object] — nothing of ours.
      const chain: string[] = [];
      for (let p = Object.getPrototypeOf(provider); p !== null; p = Object.getPrototypeOf(p)) {
        chain.push(p.constructor?.name ?? "anonymous");
      }
      expect(chain).toEqual([provider.constructor.name, "Object"]);
    }
  });

  it("imports only the contract types from the library", () => {
    const source = readFileSync(new URL("./contracts.thirdparty.test.ts", import.meta.url), "utf8");
    const providerSection = source.split("// The corpus")[0] ?? "";
    for (const forbidden of ["FakeEmbedding", "FakeLLM", "OpenAI", "isSupported", "tokenize("]) {
      expect(providerSection).not.toContain(forbidden);
    }
    // The three library imports belong to the TEST (to drive and to assert);
    // the provider classes themselves name only the contract types.
    const imports = [...source.matchAll(/^import .*? from "(\.[^"]+)";$/gm)].map((m) => m[1]);
    expect(new Set(imports)).toEqual(
      new Set(["./answer/answer.js", "./contracts.js", "./result/result.js"]),
    );
  });
});

// ---------------------------------------------------------------------------
// 2. The providers drive the port end to end
// ---------------------------------------------------------------------------

describe("third-party providers answer end to end", () => {
  const QUESTION = "Can the employee disclose confidential information?";

  it("produces a cited, gate-passing answer", async () => {
    const { generator, set } = providers();
    const res = await askWith(corpus, QUESTION, set);

    expect(res.evidence.decision).toBe(Decision.answered);
    expect(res.answer).toBeTruthy();
    expect(res.sources.length).toBeGreaterThan(0);
    expect(res.sources[0]?.document).toBe("nda");
    // Grounded: the model quoted the source, and the gate agreed.
    expect(NDA).toContain(res.answer);
    expect(generator.questions).toEqual([QUESTION]);
    expect(generator.languages).toEqual(["en"]);
  });

  it("serves a second question from the same provider set", async () => {
    const { set } = providers();
    const res = await askWith(corpus, "How much notice must the tenant give the landlord?", set);
    expect(res.evidence.decision).toBe(Decision.answered);
    expect(res.sources[0]?.document).toBe("lease");
    expect(LEASE).toContain(res.answer);
  });

  it("takes the batch path — the question is a batch of one", async () => {
    const { embedding, set } = providers();
    await askWith(corpus, QUESTION, set);
    expect(embedding.batchSizes[0]).toBe(corpus.length);
    expect(embedding.batchSizes.at(-1)).toBe(1);
  });

  it("works as a PARTIAL set — generation only, no embedding model", async () => {
    const res = await askWith(corpus, QUESTION, { generator: new InProcessGenerator() });
    expect(res.evidence.decision).toBe(Decision.answered);
    expect(res.sources[0]?.document).toBe("nda");
  });

  it("still abstains when the corpus cannot support the question", async () => {
    const { set } = providers();
    const res = await askWith(corpus, "What is the melting point of tungsten?", set);
    expect(res.evidence.decision).toBe(Decision.refused);
  });

  it("surfaces a provider failure as a rejection, never as an abstention", async () => {
    const exploding: EmbeddingProvider = {
      embed: () => Promise.reject(new Error("model call timed out after 30s")),
    };
    await expect(askWith(corpus, QUESTION, { embedding: exploding })).rejects.toThrow(/timed out/);
  });
});
