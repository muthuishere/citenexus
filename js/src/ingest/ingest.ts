// The ingest orchestrator — the TS twin of the Go core orchestrator.
//
// Pipeline (SPEC-PORTS-v1 §4): extract (Rust FFI) -> pure recursive chunker
// (js/src/chunker) -> embed each chunk via an INJECTED embedder -> upsert the
// evidence-unit rows into the Lance store (Rust FFI). The heavy stages (extract,
// store) are the native core; chunking is the pure port; embedding is the
// caller's model client (or a deterministic fake in tests).
//
// This module touches the FFI core, so like `core.ts` it stays out of the pure
// port's default build path — import it only when the native library is built.

import { extract, Store, type ExtractedBlock, type StoreRow } from "../core/core.js";
import { chunkText, DEFAULT_MAX_TOKENS, DEFAULT_OVERLAP } from "../chunker/chunker.js";
import { checkVector, type Embedder } from "./embedder.js";

export type { Embedder } from "./embedder.js";
export { isZeroVector } from "./embedder.js";

export interface IngestOptions {
  maxTokens?: number;
  overlap?: number;
}

export interface IngestResult {
  documentId: string;
  /** eu_ids of every evidence unit written, in order. */
  euIds: string[];
  /** Number of blocks the extractor produced. */
  blockCount: number;
  /** Number of evidence units (chunks) written. */
  unitCount: number;
}

/**
 * Ingest raw `bytes` of `sourceType` under `documentID` into `store`, embedding
 * each chunk with `embed`. Empty/whitespace-only blocks are skipped; each block
 * is split by the recursive chunker and each chunk becomes one evidence unit
 * with eu_id `{documentID}::{order}::{i}` (parity with the chunked builder).
 * Returns the ids written. The store is the caller's — this does not close it.
 *
 * Failure is FAIL-CLOSED and ALL-OR-NOTHING: if any chunk fails to embed, or the
 * embedder yields a vector that must not be indexed (empty, wrong-dimension,
 * non-finite, or all zeros), `ingest` rejects and writes NOTHING — nothing is
 * upserted until every vector is in hand. Skipping the failed unit was rejected:
 * a document missing one chunk is, at retrieval time, indistinguishable from a
 * document that never contained that sentence, and the caller cannot tell a
 * partially indexed corpus from a complete one. Retrying is safe — the store
 * merges on eu_id, so re-ingesting the same document is idempotent.
 */
export async function ingest(
  store: Store,
  bytes: Uint8Array,
  sourceType: string,
  documentID: string,
  embed: Embedder,
  options: IngestOptions = {},
): Promise<IngestResult> {
  const maxTokens = options.maxTokens ?? DEFAULT_MAX_TOKENS;
  const overlap = options.overlap ?? DEFAULT_OVERLAP;

  const doc = extract(bytes, sourceType, documentID);
  const rows: StoreRow[] = [];
  const euIds: string[] = [];
  let dim = 0;

  for (const block of doc.blocks as ExtractedBlock[]) {
    if (block.text.trim().length === 0) {
      continue;
    }
    const chunks = chunkText(block.text, maxTokens, overlap);
    for (let i = 0; i < chunks.length; i++) {
      const text = chunks[i]!;
      const euId = `${documentID}::${block.order}::${i}`;
      // A rejection here propagates: nothing has been upserted yet, so a failed
      // model call leaves the corpus untouched rather than quietly incomplete.
      const vector = checkVector(euId, await embed(text), dim);
      dim = vector.length;
      rows.push({
        eu_id: euId,
        document_id: documentID,
        order: block.order,
        chunk_index: i,
        text,
        vector,
      });
      euIds.push(euId);
    }
  }

  store.upsert(rows);

  return {
    documentId: documentID,
    euIds,
    blockCount: doc.blocks.length,
    unitCount: rows.length,
  };
}
