// The JS port's published model seam — the single place a provider author looks
// (ADR-0014 R1 + R4). Twin of golang/contracts and python citenexus/contracts.py.
//
// CiteNexus bundles no models. What it owes anyone who wants to supply one is an
// interface they can implement without reading our call sites. This module is
// that interface, and it imports NOTHING — not another CiteNexus module, not a
// runtime dependency — so implementing a contract costs a provider author one
// file's worth of reading.
//
// ## Two contracts, not five
//
// The Python reference publishes five (embedding, generation, completion,
// vision, reranking). This port publishes the TWO it actually consumes:
//
//     EmbeddingProvider   embed(texts)                      -> Vector[]
//     GeneratorProvider   answer(question, passage, langISO) -> string
//
// Completion, vision and reranking are absent ON PURPOSE. The JS port has no
// deep-ask decision loop (`result.ts` says so outright: "Deep-ask is Python-only
// today"), no conditional-vision path, and no rerank symbol anywhere — not even
// a candidate type a rerank contract could be spelled in terms of. A published
// contract asserts that implementing it makes the library use your provider;
// publishing one for a seam with no call site would make that assertion falsely.
// They are withheld until the port grows the consumer, not refused on principle.
//
// ## Why `embed` and not `embedMany`
//
// Python had to name the batch method `embed_many` because in Python a `str` IS
// a `Sequence[str]`, so a method spelled `embed` could not be told apart from
// the single-text shape by `isinstance` or by a type checker. That hazard is a
// property of Python's `Sequence` protocol and does NOT exist here: `string` is
// not assignable to `readonly string[]` under `tsc --strict`, and at runtime the
// two seams are not even the same KIND of value — the single-text seam is a
// FUNCTION, the batch contract is an OBJECT with an `embed` method, so `typeof`
// discriminates them with certainty (see `isEmbeddingProvider`).
//
// So this port uses the natural name — which is also, not by coincidence, the
// name the shipped `OpenAIEmbedder` already has. R4 asks for identical
// semantics across ports, not identical identifiers.
//
// ## Failure is a rejection, never a sentinel
//
// A zero vector is not an error value: it is a valid embedding of something, and
// once written it is indistinguishable from a document that genuinely embeds
// near the origin, so retrieval scores it 0 with no error and no flag
// (ADR-0014 R2). An empty string is an answer, not a failure. A provider that
// did not do the work MUST throw or reject.
//
// ## Sync or async, deliberately
//
// Every contract returns `Awaitable<T> = T | Promise<T>`, and every consumer
// `await`s. Declaring `Promise<T>` only would lock the deterministic hermetic
// fakes — the reference implementations of these very contracts — out of the
// contract, for no gain: `await` on a plain value is already correct. This
// follows the precedent R2 set in this port for `Embedder` and `Transport`.
//
// ## Nothing here mentions a transport
//
// Base URLs, headers and transports are CONSTRUCTOR parameters of the clients in
// `models/`, never contract methods, so a provider that never opens a socket
// satisfies every contract in this module (ADR-0014 R3).

/** One dense embedding. */
export type Vector = number[];

/** A value a consumer will `await`: either the value, or a promise of it. */
export type Awaitable<T> = T | Promise<T>;

/**
 * Turn texts into dense vectors. **Batch is the primitive** (ADR-0014 R1): a
 * single text is a batch of one, not a second method, because batching is where
 * the throughput is and a seam that hides it behind an optional second method is
 * a seam nobody uses.
 *
 * Implementations MUST return exactly one vector per input text, in input order,
 * and MUST reject rather than return a placeholder vector when the model did not
 * actually embed the text.
 */
export interface EmbeddingProvider {
  embed(texts: readonly string[]): Awaitable<Vector[]>;
}

/**
 * Produce a grounded answer from one already-selected passage, in the requested
 * ISO language.
 *
 * The provider is handed the passage the library chose. It does not retrieve, it
 * does not choose evidence, and it is NOT trusted: whatever it returns goes
 * through the faithfulness gate before it can become an answer. The best possible
 * generator is therefore an extractive one — quote the passage.
 *
 * Implementations MUST reject rather than return an empty string on failure.
 */
export interface GeneratorProvider {
  answer(question: string, passage: string, answerLanguage?: string): Awaitable<string>;
}

/**
 * The DEPRECATED one-text-at-a-time embedding shape — the function type the
 * ingest seam already uses, published here so `ingest/embedder.ts`'s `Embedder`
 * and this are ONE definition with two names rather than two that can drift.
 *
 * Still fully supported (`embedTexts` falls back to it), but a new provider
 * should implement `EmbeddingProvider`: this shape cannot batch, and one request
 * per Evidence Unit does not survive a real corpus.
 */
export type SingleTextEmbedder = (text: string) => Awaitable<Vector>;

/**
 * Thrown by `embedTexts` for a value that is neither embedding shape. TS has no
 * runtime types, so the dispatch helper must be able to refuse — refusing loudly
 * beats embedding nothing quietly.
 */
export class NotAnEmbedderError extends TypeError {
  constructor(received: unknown) {
    super(
      `contracts: expected an EmbeddingProvider ({ embed(texts) }) or a ` +
        `SingleTextEmbedder ((text) => vector), received ${describeKind(received)}`,
    );
    this.name = "NotAnEmbedderError";
  }
}

function describeKind(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "an array";
  return `a ${typeof value}`;
}

/**
 * Is `value` the batch contract? The single-text seam is a function and the
 * batch contract is an object with an `embed` method, so this is exact — it is
 * the runtime discrimination Python needed `embed_many` to get.
 */
export function isEmbeddingProvider(value: unknown): value is EmbeddingProvider {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { embed?: unknown }).embed === "function"
  );
}

/**
 * Embed `texts`, preferring the batch contract.
 *
 * This is the ONE place the JS port decides how to talk to an embedder — the
 * twin of Python's `contracts.embed_texts`, and the reason batching is not a
 * capability found by attribute probing. An empty input embeds nothing and calls
 * no model.
 */
export async function embedTexts(
  embedder: EmbeddingProvider | SingleTextEmbedder,
  texts: readonly string[],
): Promise<Vector[]> {
  if (texts.length === 0) return [];
  if (isEmbeddingProvider(embedder)) {
    const vectors = await embedder.embed(texts);
    if (!Array.isArray(vectors) || vectors.length !== texts.length) {
      throw new Error(
        `contracts: embedder returned ${Array.isArray(vectors) ? vectors.length : "no"} ` +
          `vectors for ${texts.length} texts; the contract is one vector per input text, ` +
          `in input order`,
      );
    }
    return vectors;
  }
  if (typeof embedder === "function") {
    const out: Vector[] = [];
    for (const text of texts) out.push(await embedder(text));
    return out;
  }
  throw new NotAnEmbedderError(embedder);
}

/** Embed a single text — a batch of one under the contract. */
export async function embedOne(
  embedder: EmbeddingProvider | SingleTextEmbedder,
  text: string,
): Promise<Vector> {
  const first = (await embedTexts(embedder, [text]))[0];
  if (first === undefined) {
    throw new Error("contracts: embedder returned nothing for a single input");
  }
  return first;
}

/**
 * Adapt a batch provider to the deprecated single-text seam, so a provider
 * written against the contract plugs straight into `ingest()` without the author
 * writing glue. The inverse of `embedTexts`'s fallback.
 */
export function singleFrom(provider: EmbeddingProvider): SingleTextEmbedder {
  return (text: string) => embedOne(provider, text);
}

/** Is `vec` the all-zeros vector — an embedding carrying no signal at all?
 *  Twin of the Python reference `citenexus.testing.fakes.is_zero_vector`. */
export function isZeroVector(vec: readonly number[]): boolean {
  return vec.every((v) => v === 0);
}

/**
 * Reject a vector that must never be indexed or scored — the belt to the
 * contracts' rejection braces. Even a seam that CAN report failure does not stop
 * a provider that returns a degenerate vector while reporting success.
 *
 * `label` names the thing being embedded (an eu_id on the write path, a document
 * id or "question" on the ask path). `dim` is the dimensionality established by
 * this run — 0 for the first vector, which defines it.
 *
 * Five rejections, in THIS order — the order is part of the contract, not an
 * implementation detail. A vector can fail more than one rule at once, and three
 * ports that disagree about which error to report are three ports that disagree
 * about the contract. It is pinned by `conformance/cases/vector_validation.json`,
 * replayed by `python/tests/conformance/test_vector_validation_vectors.py`,
 * `golang/contracts/vector_validation_test.go` and `contracts.vector.test.ts`.
 *
 *   1. not a vector at all — a payload that is not an array of numbers. Go needs
 *      no equivalent: `[]float64` makes it unrepresentable, which is why the
 *      conformance vector keeps these cases in their own bucket.
 *   2. empty — unguarded it surfaces much later as a dimension error deep inside
 *      the store, misattributed to storage rather than to the model.
 *   3. inconsistent dimension — one run's vectors must be mutually comparable.
 *   4. non-finite — NaN/±Inf. Every comparison with NaN is false, so ranking
 *      comes to depend on the sort algorithm rather than on the data.
 *   5. all-zeros — the silent poison ADR-0014 names, which cosine scores as 0
 *      with no error and no flag.
 *
 * Lives here, not in `ingest/`, so the write path and the ask path cannot
 * diverge on what "a vector we refuse to index" means.
 */
export function checkVector(label: string, vec: unknown, dim: number): Vector {
  if (!Array.isArray(vec) || vec.some((v) => typeof v !== "number")) {
    throw new TypeError(`embedder returned a non-vector for ${label}`);
  }
  const v = vec as Vector;
  if (v.length === 0) {
    throw new Error(`embedder returned an empty vector for ${label}`);
  }
  if (dim > 0 && v.length !== dim) {
    throw new Error(
      `embedder returned a ${v.length}-dim vector for ${label}; this run is ${dim}-dim`,
    );
  }
  if (v.some((x) => !Number.isFinite(x))) {
    throw new Error(`embedder returned a non-finite vector for ${label}`);
  }
  if (isZeroVector(v)) {
    throw new Error(
      `embedder returned the zero vector for ${label} — it carries no signal ` +
        `and would rank meaninglessly against every query`,
    );
  }
  return v;
}
