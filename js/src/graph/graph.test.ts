import { describe, it, expect } from "vitest";
import { loadCase } from "../conform/fixtures.js";
import { buildComentionGraph, type GraphRow, type GraphIndex } from "./graph.js";

// Proven against the shared fixture — every case must match the Python reference
// citenexus.graph.store.build_comention_graph exactly. Follows the §4 exemplar:
// load conformance/cases/graph_comention.json, assert deep equality over ALL
// cases, no leniency.
interface GraphCase {
  name: string;
  rows: GraphRow[];
  expected: GraphIndex;
}

describe("co-mention graph conformance", () => {
  const { cases } = loadCase<{ cases: GraphCase[] }>("graph_comention.json");

  it("has cases", () => {
    expect(cases.length).toBeGreaterThan(0);
  });

  for (const c of cases) {
    it(c.name, () => {
      expect(buildComentionGraph(c.rows)).toEqual(c.expected);
    });
  }
});
