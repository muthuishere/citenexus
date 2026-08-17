import { describe, expect, it } from "vitest";

import type { EmbeddingProvider, GeneratorProvider, Vector } from "../contracts.js";
import { loadCase } from "../conform/fixtures.js";
import { Decision } from "../result/result.js";
import { ask, askWith, type CorpusDoc } from "./answer.js";

// ---------------------------------------------------------------------------
// Doubles written from OUTSIDE: they name only the published contract shapes.
// ---------------------------------------------------------------------------

/** One slot per letter; enough for relative ranking, wholly independent of the
 *  library's own fakes. */
function letterVec(text: string): Vector {
  const vec = new Array<number>(26).fill(0);
  for (const ch of text.toLowerCase()) {
    const i = ch.charCodeAt(0) - 97;
    if (i >= 0 && i < 26) vec[i] = (vec[i] ?? 0) + 1;
  }
  return vec;
}

class StubEmbedding implements EmbeddingProvider {
  batches: string[][] = [];
  constructor(
    private readonly vector: (text: string) => Vector = letterVec,
    private readonly fail?: Error,
  ) {}
  async embed(texts: readonly string[]): Promise<Vector[]> {
    this.batches.push([...texts]);
    if (this.fail) throw this.fail;
    return texts.map((t) => this.vector(t));
  }
}

class StubGenerator implements GeneratorProvider {
  calls: string[] = [];
  languages: (string | undefined)[] = [];
  constructor(
    private readonly reply?: string,
    private readonly fail?: Error,
  ) {}
  async answer(question: string, passage: string, answerLanguage?: string): Promise<string> {
    this.calls.push(question);
    this.languages.push(answerLanguage);
    if (this.fail) throw this.fail;
    return this.reply ?? passage; // extractive: quote the evidence
  }
}

const MODEL_DOWN = new Error("model call timed out after 30s");

const NDA = "The employee shall not disclose confidential information to any third party.";
const LEASE = "The tenant shall give the landlord thirty days written notice.";
const miniCorpus: CorpusDoc[] = [
  { document_id: "nda", text: NDA },
  { document_id: "lease", text: LEASE },
];
const NDA_QUESTION = "Can the employee disclose confidential information?";

// ---------------------------------------------------------------------------
// 1. The pinned entry point is unchanged — ask IS askWith with no providers
// ---------------------------------------------------------------------------

interface E2EFixture {
  corpus: CorpusDoc[];
  top_k: number;
  cases: { question: string }[];
}

/** Vector counts, pinned. A vector silently dropped from the fixture is a
 *  weakened contract that no per-case assertion can see. `top_k` is a scalar
 *  parameter, not a count, so it is pinned separately. */
const EXPECTED_COUNTS: Record<string, number> = { corpus: 3, cases: 4 };
const EXPECTED_TOP_K = 5;

describe("askWith with an empty provider set is ask", () => {
  const fixture = loadCase<E2EFixture>("e2e_hermetic.json");

  it("vector counts are pinned", () => {
    expect({ corpus: fixture.corpus.length, cases: fixture.cases.length }).toEqual(
      EXPECTED_COUNTS,
    );
    expect(fixture.top_k).toBe(EXPECTED_TOP_K);
  });

  for (const c of fixture.cases) {
    it(`askWith(${JSON.stringify(c.question)}) === ask(...)`, async () => {
      const want = ask(fixture.corpus, c.question, fixture.top_k);
      const got = await askWith(fixture.corpus, c.question, { topK: fixture.top_k });
      expect(got).toEqual(want);
    });
  }
});

// ---------------------------------------------------------------------------
// 2. Injected providers actually drive the flow
// ---------------------------------------------------------------------------

describe("askWith with injected providers", () => {
  it("produces a cited, verbatim answer", async () => {
    const embedding = new StubEmbedding();
    const generator = new StubGenerator();
    const res = await askWith(miniCorpus, NDA_QUESTION, { embedding, generator });

    expect(res.evidence.decision).toBe(Decision.answered);
    expect(res.sources[0]?.document).toBe("nda");
    expect(NDA).toContain(res.answer);
    expect(generator.calls).toEqual([NDA_QUESTION]);
    expect(generator.languages).toEqual(["en"]);
  });

  it("takes the batch path, and the question is a batch of one", async () => {
    const embedding = new StubEmbedding();
    await askWith(miniCorpus, NDA_QUESTION, { embedding });
    expect(embedding.batches.length).toBe(2);
    expect(embedding.batches[0]).toHaveLength(miniCorpus.length);
    expect(embedding.batches[1]).toHaveLength(1);
  });

  it("accepts a PARTIAL provider set — generation only", async () => {
    const res = await askWith(miniCorpus, NDA_QUESTION, { generator: new StubGenerator() });
    expect(res.evidence.decision).toBe(Decision.answered);
    expect(res.sources[0]?.document).toBe("nda");
  });

  it("accepts a PARTIAL provider set — embedding only", async () => {
    const res = await askWith(miniCorpus, NDA_QUESTION, { embedding: new StubEmbedding() });
    expect(res.evidence.decision).toBe(Decision.answered);
  });

  it("accepts a single-text embedder too — the deprecated shape still works", async () => {
    const seen: string[] = [];
    const res = await askWith(miniCorpus, NDA_QUESTION, {
      embedding: (text: string) => {
        seen.push(text);
        return letterVec(text);
      },
    });
    expect(res.evidence.decision).toBe(Decision.answered);
    expect(seen).toHaveLength(miniCorpus.length + 1); // corpus + the question
  });

  it("still abstains when nothing in the corpus is relevant", async () => {
    const res = await askWith(miniCorpus, "zzzz qqqq", {
      embedding: new StubEmbedding(),
      generator: new StubGenerator(),
    });
    expect(res.evidence.decision).toBe(Decision.refused);
  });
});

// ---------------------------------------------------------------------------
// 3. A provider failure is a REJECTION, never a refusal
// ---------------------------------------------------------------------------

describe("a provider failure is not an abstention", () => {
  // A refusal is a FINDING about the evidence. A dead model is not one — saying
  // so would be the same class of lie as the zero vector R2 removed.
  it("an embedding failure rejects", async () => {
    await expect(
      askWith(miniCorpus, NDA_QUESTION, {
        embedding: new StubEmbedding(letterVec, MODEL_DOWN),
      }),
    ).rejects.toThrow(/timed out/);
  });

  it("a generator failure rejects", async () => {
    await expect(
      askWith(miniCorpus, NDA_QUESTION, {
        generator: new StubGenerator(undefined, MODEL_DOWN),
      }),
    ).rejects.toThrow(/timed out/);
  });
});

// ---------------------------------------------------------------------------
// 4. Degenerate vectors from a NON-failing provider are still refused
// ---------------------------------------------------------------------------

describe("the write-path vector guard applies to the ask path", () => {
  it("rejects the zero vector", async () => {
    await expect(
      askWith(miniCorpus, NDA_QUESTION, {
        embedding: new StubEmbedding(() => new Array<number>(26).fill(0)),
      }),
    ).rejects.toThrow(/zero vector/);
  });

  it("rejects an empty vector", async () => {
    await expect(
      askWith(miniCorpus, NDA_QUESTION, { embedding: new StubEmbedding(() => []) }),
    ).rejects.toThrow(/empty vector/);
  });

  it("rejects a run whose dimensions disagree", async () => {
    let n = 0;
    await expect(
      askWith(miniCorpus, NDA_QUESTION, {
        embedding: new StubEmbedding(() => new Array<number>(++n * 4).fill(1)),
      }),
    ).rejects.toThrow(/-dim vector/);
  });

  it("rejects a non-finite vector", async () => {
    await expect(
      askWith(miniCorpus, NDA_QUESTION, { embedding: new StubEmbedding(() => [1, NaN, 1]) }),
    ).rejects.toThrow(/non-finite/);
  });

  it("accepts a provider whose dimensionality is nothing like the fake's", async () => {
    const res = await askWith(miniCorpus, NDA_QUESTION, {
      embedding: new StubEmbedding((text) => {
        const v = letterVec(text);
        return [(v[4] ?? 0) + 1, (v[3] ?? 0) + 1];
      }),
    });
    expect(res.evidence.decision).toBe(Decision.answered);
  });
});

// ---------------------------------------------------------------------------
// 5. The gate still runs on injected output — this is the product
// ---------------------------------------------------------------------------

describe("the faithfulness gate does not soften for an injected model", () => {
  it("refuses a paraphrasing generator", async () => {
    const res = await askWith(miniCorpus, NDA_QUESTION, {
      generator: new StubGenerator("Yes, the employee may freely share everything."),
    });
    expect(res.evidence.decision).toBe(Decision.refused);
    expect(res.answer).not.toContain("freely");
  });

  it("refuses an answer carrying one word the passage does not contain", async () => {
    // NOTE: the gate on this path is the FROZEN §4 v1 predicate, which is known
    // to accept negation-deletion and role-inversion (that is what
    // spikes/library-stress measures and verify-v2 fixes). askWith deliberately
    // does not swap the gate: `ask` is pinned by e2e_hermetic.json and the two
    // must stay ONE flow.
    const res = await askWith(miniCorpus, NDA_QUESTION, {
      generator: new StubGenerator(
        "The employee shall not disclose confidential information to any competitor.",
      ),
    });
    expect(res.evidence.decision).toBe(Decision.refused);
  });
});
