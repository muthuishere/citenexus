import { describe, it, expect } from "vitest";
import { loadCase } from "./fixtures.js";
import { tokenize } from "../tokenize/tokenize.js";
import { bm25, type Bm25Row, type Bm25Result } from "../bm25/bm25.js";
import { chunkText } from "../chunker/chunker.js";
import { hasRelevanceOverlap, isSupported } from "../gate/gate.js";

// The ADR-0006 anti-drift corpus. The gate, bm25, and chunker STAY per host
// language; this multilingual/Unicode-edge suite is what pins them against
// drift where it actually happens — the tokenizer's case-folding (Turkish
// dotted İ, German ß), Unicode normalization (NFC vs NFD), CJK, and combining
// marks. Every vector's expected output is generated from the Python reference.
interface Multilingual {
  tokenize: { input: string; tokens: string[] }[];
  bm25: { name: string; rows: Bm25Row[]; query: string; expected: Bm25Result[] }[];
  chunker: { text: string; max_tokens: number; overlap: number; chunks: string[] }[];
  gate: {
    supported: { answer: string; passage: string; supported: boolean }[];
    relevance: { query: string; passage: string; relevant: boolean }[];
  };
}

describe("multilingual conformance", () => {
  const m = loadCase<Multilingual>("multilingual.json");

  it("has cases in every section", () => {
    expect(m.tokenize.length).toBeGreaterThan(0);
    expect(m.bm25.length).toBeGreaterThan(0);
    expect(m.chunker.length).toBeGreaterThan(0);
    expect(m.gate.supported.length).toBeGreaterThan(0);
    expect(m.gate.relevance.length).toBeGreaterThan(0);
  });

  for (const c of m.tokenize) {
    it(`tokenize(${JSON.stringify(c.input)})`, () => {
      expect(tokenize(c.input)).toEqual(c.tokens);
    });
  }

  for (const c of m.bm25) {
    it(`bm25 ${c.name}`, () => {
      expect(bm25(c.rows, c.query)).toEqual(c.expected);
    });
  }

  for (const [i, c] of m.chunker.entries()) {
    it(`chunker case ${i} (max=${c.max_tokens}, overlap=${c.overlap})`, () => {
      expect(chunkText(c.text, c.max_tokens, c.overlap)).toEqual(c.chunks);
    });
  }

  for (const c of m.gate.supported) {
    it(`isSupported(${JSON.stringify(c.answer)}, ${JSON.stringify(c.passage)})`, () => {
      expect(isSupported(c.answer, c.passage)).toBe(c.supported);
    });
  }

  for (const c of m.gate.relevance) {
    it(`hasRelevanceOverlap(${JSON.stringify(c.query)}, ${JSON.stringify(c.passage)})`, () => {
      expect(hasRelevanceOverlap(c.query, c.passage)).toBe(c.relevant);
    });
  }
});
