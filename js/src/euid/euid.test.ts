import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import {
  blockBuilderEuIds,
  chunkedBuilderEuIds,
  sha256Hex,
  type Block,
} from "./euid.js";

// Evidence-Unit id builders proven against the shared fixture — every case must
// match the Python reference exactly (builder.py + chunked_builder.py + chunker.py).
// Follows the tokenize EXEMPLAR: load conformance/cases/eu_ids.json, assert deep
// equality over ALL cases, no leniency.
interface EuIdCase {
  name: string;
  document_id: string;
  blocks: Block[];
  chunk_max_tokens: number;
  chunk_overlap: number;
  block_builder_eu_ids: string[];
  chunked_builder_eu_ids: string[];
}

interface EuIdFixture {
  cases: EuIdCase[];
  checksum_example: { raw_utf8: string; sha256: string };
}

describe("eu_id builder conformance", () => {
  const fixture = loadCase<EuIdFixture>("eu_ids.json");
  const cases = fixture.cases;

  it("has cases", () => {
    expect(cases.length).toBeGreaterThan(0);
  });

  for (const c of cases) {
    it(`block builder: ${c.name}`, () => {
      expect(blockBuilderEuIds(c.document_id, c.blocks)).toEqual(
        c.block_builder_eu_ids,
      );
    });

    it(`chunked builder: ${c.name}`, () => {
      expect(
        chunkedBuilderEuIds(
          c.document_id,
          c.blocks,
          c.chunk_max_tokens,
          c.chunk_overlap,
        ),
      ).toEqual(c.chunked_builder_eu_ids);
    });
  }

  it("checksum matches SHA-256 hex lowercase", () => {
    expect(sha256Hex(fixture.checksum_example.raw_utf8)).toEqual(
      fixture.checksum_example.sha256,
    );
  });
});
