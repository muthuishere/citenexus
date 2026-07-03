// BM25-lite ranking (SPEC-PORTS-v1 §4/§10), parity with the Python reference
// citenexus.storage.bm25.Bm25TextSearch.
//
// Tokenizer = the pinned §4 tokenizer. Query terms are taken as a SET. Rows with
// a total score of 0 are dropped; the survivors are sorted DESCENDING by score
// with a stable tie-break on original input row order. Scores round to 1e-6.

import { tokenize } from "../tokenize/tokenize.js";

const K1 = 1.5;
const B = 0.75;

export interface Bm25Row {
  eu_id: string;
  text: string;
}

export interface Bm25Result {
  eu_id: string;
  score: number;
}

function round6(x: number): number {
  return Math.round(x * 1e6) / 1e6;
}

/** Rank `rows` by BM25 against `query`; ordered (eu_id, score) survivors. */
export function bm25(rows: Bm25Row[], query: string): Bm25Result[] {
  if (rows.length === 0) return [];
  const terms = tokenize(query);
  if (terms.length === 0) return [];

  const tokenized = rows.map((row) => tokenize(row.text ?? ""));
  const nDocs = rows.length;
  const totalLen = tokenized.reduce((sum, toks) => sum + toks.length, 0);
  const avgLen = totalLen / nDocs || 1.0;

  const queryTerms = new Set(terms);
  const docFreq = new Map<string, number>();
  for (const term of queryTerms) {
    let nT = 0;
    for (const toks of tokenized) {
      if (toks.includes(term)) nT += 1;
    }
    docFreq.set(term, nT);
  }

  const scored: { score: number; idx: number }[] = [];
  for (let idx = 0; idx < tokenized.length; idx += 1) {
    const toks = tokenized[idx]!;
    const counts = new Map<string, number>();
    for (const t of toks) counts.set(t, (counts.get(t) ?? 0) + 1);
    const docLen = toks.length;
    let score = 0.0;
    for (const term of queryTerms) {
      const tf = counts.get(term) ?? 0;
      if (tf === 0) continue;
      const nT = docFreq.get(term)!;
      const idf = Math.log(1.0 + (nDocs - nT + 0.5) / (nT + 0.5));
      const norm = (tf * (K1 + 1.0)) / (tf + K1 * (1.0 - B + (B * docLen) / avgLen));
      score += idf * norm;
    }
    if (score > 0.0) scored.push({ score, idx });
  }

  scored.sort((a, b) => b.score - a.score || a.idx - b.idx);
  return scored.map(({ score, idx }) => ({ eu_id: rows[idx]!.eu_id, score: round6(score) }));
}
