// The model seam and the write-path vector guard. Deliberately SEPARATE from
// ingest.ts, which loads the native FFI core at import time: the contract a
// provider has to satisfy, and the check that keeps a degenerate vector out of
// the corpus, are pure TypeScript and stay importable and unit-tested with no
// native library built (ADR-0014 R2). Go's twin is golang/ingest/embedder.go.

/** A dense embedder: text in, one vector out. Injected by the caller.
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
export type Embedder = (text: string) => number[] | Promise<number[]>;

/** Is `vec` the all-zeros vector — an embedding carrying no signal at all?
 *  Twin of the Python reference `citenexus.testing.fakes.is_zero_vector`,
 *  promoted from test-only helper to write-path guard. */
export function isZeroVector(vec: readonly number[]): boolean {
  return vec.every((v) => v === 0);
}

/** Reject a vector that must never become an evidence-unit row — the belt to the
 *  async seam's braces. Even a provider that reports success must not be able to
 *  poison the corpus with a degenerate vector.
 *
 *  `dim` is the dimensionality established by this ingest run (0 for the first
 *  vector, which defines it). */
export function checkVector(euId: string, vec: unknown, dim: number): number[] {
  if (!Array.isArray(vec) || vec.some((v) => typeof v !== "number")) {
    throw new TypeError(`ingest: embedder returned a non-vector for ${euId}`);
  }
  const v = vec as number[];
  if (v.length === 0) {
    throw new Error(`ingest: embedder returned an empty vector for ${euId}`);
  }
  if (dim > 0 && v.length !== dim) {
    throw new Error(
      `ingest: embedder returned a ${v.length}-dim vector for ${euId}; this run is ${dim}-dim`,
    );
  }
  if (v.some((x) => !Number.isFinite(x))) {
    throw new Error(`ingest: embedder returned a non-finite vector for ${euId}`);
  }
  if (isZeroVector(v)) {
    throw new Error(
      `ingest: embedder returned the zero vector for ${euId} — it carries no signal ` +
        `and would rank meaninglessly against every query`,
    );
  }
  return v;
}

