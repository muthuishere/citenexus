// Deterministic fakes for the hermetic ask flow (SPEC-PORTS-v1 §0/§4).
//
// These are the offline stand-ins that make cite-or-abstain provable without a
// model server: a hash-bucket embedder, an evidence-echoing LLM, and a cosine
// that is a plain dot product (vectors arrive L2-normalized). Parity with the
// Python reference citenexus.testing.fakes.

import { createHash } from "node:crypto";
import { tokenize } from "../tokenize/tokenize.js";

/** Embedding dimensionality (§4). */
export const EMBED_DIM = 64;

/**
 * Hash-bucket bag-of-tokens embedder. Each token lands in one of EMBED_DIM
 * buckets via sha1(token) mod EMBED_DIM; the vector is then L2-normalized (an
 * all-zero vector stays zero). Deterministic and language-agnostic.
 */
export class FakeEmbedding {
  embed(text: string): number[] {
    const vec = new Array<number>(EMBED_DIM).fill(0);
    for (const token of tokenize(text)) {
      const hex = createHash("sha1").update(token, "utf8").digest("hex");
      const idx = Number(BigInt("0x" + hex) % BigInt(EMBED_DIM));
      vec[idx] = (vec[idx] ?? 0) + 1.0;
    }
    let sumSquares = 0;
    for (const v of vec) sumSquares += v * v;
    const norm = Math.sqrt(sumSquares);
    if (norm === 0) return vec;
    return vec.map((v) => v / norm);
  }
}

/** Evidence-echoing generator: the answer is the cited passage, verbatim. */
export class FakeLLM {
  answer(_question: string, passage: string): string {
    return passage;
  }
}

/** Cosine similarity of two already-normalized vectors: a plain dot product. */
export function cosine(a: readonly number[], b: readonly number[]): number {
  let dot = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    dot += (a[i] ?? 0) * (b[i] ?? 0);
  }
  return dot;
}
