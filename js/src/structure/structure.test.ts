import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import {
  buildStructure,
  type StructureBlock,
  type StructureIndex,
} from "./structure.js";

// Proven against the shared fixture — every case must match the Python reference
// citenexus.evidence.structure.build_structure exactly. Follows the §4 exemplar:
// load conformance/cases/structure.json, assert deep equality over ALL cases,
// no leniency.
interface StructureCase {
  name: string;
  document_id: string;
  structure_type: string;
  blocks: StructureBlock[];
  expected: StructureIndex;
}

/** Vector counts, pinned. A vector silently dropped from the fixture is a
 *  weakened contract that no per-case assertion can see. */
const EXPECTED_COUNTS: Record<string, number> = { cases: 11 };

describe("structure index conformance", () => {
  const { cases } = loadCase<{ cases: StructureCase[] }>("structure.json");

  it("vector counts are pinned", () => {
    expect({ cases: cases.length }).toEqual(EXPECTED_COUNTS);
  });

  for (const c of cases) {
    it(c.name, () => {
      const doc = {
        document_id: c.document_id,
        structure_type: c.structure_type,
        blocks: c.blocks,
      };
      expect(buildStructure(doc)).toEqual(c.expected);
    });
  }
});
