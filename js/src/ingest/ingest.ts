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

/** A dense embedder: text in, one vector out. Injected by the caller. */
export type Embedder = (text: string) => number[];

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
 */
export function ingest(
  store: Store,
  bytes: Uint8Array,
  sourceType: string,
  documentID: string,
  embed: Embedder,
  options: IngestOptions = {},
): IngestResult {
  const maxTokens = options.maxTokens ?? DEFAULT_MAX_TOKENS;
  const overlap = options.overlap ?? DEFAULT_OVERLAP;

  const doc = extract(bytes, sourceType, documentID);
  const rows: StoreRow[] = [];
  const euIds: string[] = [];

  for (const block of doc.blocks as ExtractedBlock[]) {
    if (block.text.trim().length === 0) {
      continue;
    }
    const chunks = chunkText(block.text, maxTokens, overlap);
    for (let i = 0; i < chunks.length; i++) {
      const text = chunks[i]!;
      const euId = `${documentID}::${block.order}::${i}`;
      rows.push({
        eu_id: euId,
        document_id: documentID,
        order: block.order,
        chunk_index: i,
        text,
        vector: embed(text),
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
