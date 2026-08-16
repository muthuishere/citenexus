// The model seam and the write-path vector guard. Deliberately SEPARATE from
// ingest.ts, which loads the native FFI core at import time: the contract a
// provider has to satisfy, and the check that keeps a degenerate vector out of
// the corpus, are pure TypeScript and stay importable and unit-tested with no
// native library built (ADR-0014 R2). Go's twin is golang/ingest/embedder.go.

import {
  checkVector as checkVectorContract,
  isZeroVector as isZeroVectorContract,
  type SingleTextEmbedder,
} from "../contracts.js";

/** A dense embedder: text in, one vector out. Injected by the caller.
 *
 * It is an ALIAS of the published `contracts.SingleTextEmbedder`, not a second
 * declaration of the same shape (ADR-0014 R4). One definition, two names: a
 * provider written against the published contract plugs in here with no
 * conversion, and the two cannot drift apart. New providers should implement
 * `contracts.EmbeddingProvider` instead — batch is the primitive, and
 * `contracts.singleFrom` adapts one to this seam.
 *
 * ASYNC-CAPABLE (ADR-0014 R2). The old `=> number[]` was unsatisfiable by any
 * network- or model-backed provider: `tsc --strict` rejected every async
 * embedder outright, and casting past it put a `Promise` in `row.vector` (which
 * serialises to `{}` for the FFI store) while the rejection went unhandled, so a
 * failed model call was invisible to `ingest()`. A synchronous embedder — the
 * hermetic fakes — is still valid; `ingest` awaits either.
 *
 * Failure is expressed by REJECTING (or throwing), never by a placeholder
 * vector: a zero vector is not an error value, it is a valid embedding of
 * something, and once written it is indistinguishable from a document that
 * genuinely embeds near the origin. */
export type Embedder = SingleTextEmbedder;

/** Is `vec` the all-zeros vector — an embedding carrying no signal at all?
 *  Twin of the Python reference `citenexus.testing.fakes.is_zero_vector`.
 *  Delegates to the published contracts helper so the write path and the ask
 *  path share ONE definition. */
export function isZeroVector(vec: readonly number[]): boolean {
  return isZeroVectorContract(vec);
}

/** Reject a vector that must never become an evidence-unit row — the belt to the
 *  async seam's braces. Even a provider that reports success must not be able to
 *  poison the corpus with a degenerate vector.
 *
 *  `dim` is the dimensionality established by this ingest run (0 for the first
 *  vector, which defines it). */
export function checkVector(euId: string, vec: unknown, dim: number): number[] {
  // The rejections themselves live in `contracts.checkVector` so the ingest
  // write path and the ask path cannot diverge on what "a vector we refuse to
  // index" means; ingest only adds its own prefix. The error CLASS is preserved
  // (TypeError for a non-vector, Error otherwise) — only the message is framed.
  try {
    return checkVectorContract(euId, vec, dim);
  } catch (err) {
    if (err instanceof Error) err.message = `ingest: ${err.message}`;
    throw err;
  }
}

