// The pinned CiteNexus recursive chunker (SPEC-PORTS-v1 §4). Parity with the
// Python reference citenexus.evidence.chunker.chunk_text.
//
// Recursive, boundary-aware splitting: keep whole paragraphs together; when a
// unit exceeds the token bound, recurse to the next finer boundary (paragraph ->
// line -> sentence -> word), then greedily pack pieces into size-bounded chunks
// with a trailing-word overlap window. "Token" count is whitespace-split words.
//
// RE2/lookbehind note: sentence splitting matches Python's (?<=[.!?])\s+ by
// scanning whitespace runs that immediately follow a . ! or ? and splitting
// there, keeping the punctuation on the left piece.

const PARAGRAPH = /\n\s*\n/;
const LINE = /\n/;
const WHITESPACE = /\s+/;

export const DEFAULT_MAX_TOKENS = 450;
export const DEFAULT_OVERLAP = 60;

function tokens(text: string): number {
  return text.split(WHITESPACE).filter((w) => w.length > 0).length;
}

/** Split on the coarsest boundary that yields more than one piece. */
function splitUnits(text: string): string[] {
  for (const pattern of [PARAGRAPH, LINE]) {
    const pieces = text
      .split(pattern)
      .map((p) => p.trim())
      .filter((p) => p.length > 0);
    if (pieces.length > 1) {
      return pieces;
    }
  }
  // Sentence boundary: whitespace runs immediately following . ! or ?.
  const sentences = splitSentences(text)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
  if (sentences.length > 1) {
    return sentences;
  }
  // Finest boundary: individual words.
  return text.split(WHITESPACE).filter((w) => w.length > 0);
}

/** Mirror Python re.split(r"(?<=[.!?])\s+", text) without lookbehind. */
function splitSentences(text: string): string[] {
  const out: string[] = [];
  let start = 0;
  const re = /\s+/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const prev = text[m.index - 1];
    if (prev === "." || prev === "!" || prev === "?") {
      out.push(text.slice(start, m.index));
      start = m.index + m[0].length;
    }
  }
  out.push(text.slice(start));
  return out;
}

/** Recursively split until every piece fits max_tokens. */
function fitPieces(text: string, maxTokens: number): string[] {
  if (tokens(text) <= maxTokens) {
    return [text];
  }
  const units = splitUnits(text);
  if (units.length === 1) {
    // A single oversized word-run: hard-split into max_tokens windows.
    const words = units[0]!.split(WHITESPACE).filter((w) => w.length > 0);
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

/** Split `text` into bounded, overlapping, boundary-respecting chunks. */
export function chunkText(
  text: string,
  maxTokens: number = DEFAULT_MAX_TOKENS,
  overlap: number = DEFAULT_OVERLAP,
): string[] {
  if (maxTokens < 1) {
    throw new Error("max_tokens must be >= 1");
  }
  const stripped = text.trim();
  if (stripped.length === 0) {
    return [];
  }
  if (tokens(stripped) <= maxTokens) {
    return [stripped];
  }
  const clampedOverlap = Math.max(0, Math.min(overlap, maxTokens - 1));
  const pieces = fitPieces(stripped, maxTokens);
  return pack(pieces, maxTokens, clampedOverlap);
}
