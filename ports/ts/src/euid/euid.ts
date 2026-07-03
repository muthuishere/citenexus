// The pinned CiteNexus Evidence-Unit id builders (SPEC-PORTS-v1 §4/§10).
//
// Frozen contract, mirroring the Python reference:
//   - citenexus.evidence.builder.build_evidence_units
//   - citenexus.evidence.chunked_builder.build_chunked_units
//   - citenexus.evidence.chunker.chunk_text
//
// Block builder: each block whose text is NON-empty after trimming maps to one
// unit; empty/whitespace-only blocks are skipped. eu_id = "{document_id}::{order}".
// Chunked builder: an oversized block is split by the recursive chunker into
// child units with eu_id = "{document_id}::{order}::{i}".

import { createHash } from "node:crypto";

export interface Block {
  order: number;
  kind: string;
  text: string;
  page?: number;
}

const PARAGRAPH = /\n\s*\n/;
const LINE = /\n/;
const SENTENCE = /(?<=[.!?])\s+/;
const WORD = /\s+/;

/** Word-count token approximation — Python str.split() semantics. */
function tokens(text: string): number {
  return text.split(WORD).filter((p) => p.length > 0).length;
}

/** Split on the coarsest boundary that yields more than one non-empty piece. */
function splitUnits(text: string): string[] {
  for (const pattern of [PARAGRAPH, LINE, SENTENCE]) {
    const pieces = text
      .split(pattern)
      .map((p) => p.trim())
      .filter((p) => p.length > 0);
    if (pieces.length > 1) {
      return pieces;
    }
  }
  return text.split(WORD).filter((w) => w.length > 0);
}

/** Recursively split until every piece fits max_tokens. */
function fitPieces(text: string, maxTokens: number): string[] {
  if (tokens(text) <= maxTokens) {
    return [text];
  }
  const units = splitUnits(text);
  if (units.length === 1) {
    const words = units[0]!.split(WORD).filter((w) => w.length > 0);
    const out: string[] = [];
    for (let i = 0; i < words.length; i += maxTokens) {
      out.push(words.slice(i, i + maxTokens).join(" "));
    }
    return out;
  }
  const out: string[] = [];
  for (const unit of units) {
    out.push(...fitPieces(unit, maxTokens));
  }
  return out;
}

/** The trailing pieces whose combined size is within overlap tokens. */
function overlapTail(pieces: string[], overlap: number): string[] {
  if (overlap <= 0) {
    return [];
  }
  const tail: string[] = [];
  let size = 0;
  for (let i = pieces.length - 1; i >= 0; i--) {
    const piece = pieces[i]!;
    const n = tokens(piece);
    if (size + n > overlap) {
      break;
    }
    tail.unshift(piece);
    size += n;
  }
  return tail;
}

/** Greedily pack pieces into chunks; carry an overlap tail between chunks. */
function pack(pieces: string[], maxTokens: number, overlap: number): string[] {
  const chunks: string[] = [];
  let current: string[] = [];
  let size = 0;
  for (const piece of pieces) {
    const n = tokens(piece);
    if (current.length > 0 && size + n > maxTokens) {
      chunks.push(current.join("\n"));
      const tail = overlapTail(current, overlap);
      current = tail.slice();
      size = current.reduce((acc, p) => acc + tokens(p), 0);
    }
    current.push(piece);
    size += n;
  }
  if (current.length > 0) {
    chunks.push(current.join("\n"));
  }
  return chunks;
}

/** Split text into bounded, overlapping, boundary-respecting chunks. */
export function chunkText(
  text: string,
  maxTokens = 450,
  overlap = 60,
): string[] {
  if (maxTokens < 1) {
    throw new Error("maxTokens must be >= 1");
  }
  const stripped = text.trim();
  if (stripped.length === 0) {
    return [];
  }
  if (tokens(stripped) <= maxTokens) {
    return [stripped];
  }
  const boundedOverlap = Math.max(0, Math.min(overlap, maxTokens - 1));
  const pieces = fitPieces(stripped, maxTokens);
  return pack(pieces, maxTokens, boundedOverlap);
}

/** eu_ids for the one-block-one-unit builder; empties skipped. */
export function blockBuilderEuIds(documentId: string, blocks: Block[]): string[] {
  return blocks
    .filter((b) => b.text.trim().length > 0)
    .map((b) => `${documentId}::${b.order}`);
}

/** eu_ids for the chunked builder; each block → one child per chunk. */
export function chunkedBuilderEuIds(
  documentId: string,
  blocks: Block[],
  maxTokens = 450,
  overlap = 60,
): string[] {
  const out: string[] = [];
  for (const block of blocks) {
    if (block.text.trim().length === 0) {
      continue;
    }
    const chunks = chunkText(block.text, maxTokens, overlap);
    for (let i = 0; i < chunks.length; i++) {
      out.push(`${documentId}::${block.order}::${i}`);
    }
  }
  return out;
}

/** SHA-256 hex (lowercase) of the UTF-8 bytes of `raw`. */
export function sha256Hex(raw: string): string {
  return createHash("sha256").update(raw, "utf8").digest("hex");
}
