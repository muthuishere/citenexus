import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import { chunkText } from "./chunker.js";

// Proven against the shared fixture — every case must match the Python reference
// citenexus.evidence.chunker.chunk_text exactly. Follows the §4 exemplar: load
// conformance/cases/chunker.json, assert deep equality over ALL cases, no leniency.
interface ChunkerCase {
  text: string;
  max_tokens: number;
  overlap: number;
  chunks: string[];
}

describe("chunker conformance", () => {
  const cases = loadCase<ChunkerCase[]>("chunker.json");

  it("has cases", () => {
    expect(cases.length).toBeGreaterThan(0);
  });

  for (const [i, c] of cases.entries()) {
    it(`chunkText case ${i} (max=${c.max_tokens}, overlap=${c.overlap})`, () => {
      expect(chunkText(c.text, c.max_tokens, c.overlap)).toEqual(c.chunks);
    });
  }
});
