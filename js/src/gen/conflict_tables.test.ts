// Drift guard: the bundled ADR-0007 conflict tables must equal the canonical
// conformance/conflict.json.
//
// Runtime code imports the GENERATED module (so the published package is
// self-contained — package.json `files` is ["dist"]); the tests read
// conformance/ directly. The generator is python/scripts/gen_conflict_tables.py,
// which emits this module together with the Go and Python copies, so a hand-edit
// here is a divergence from the cross-language contract, not a local change.
import { describe, expect, it } from "vitest";

import { loadData } from "../conform/fixtures.js";
import {
  CONFLICT_ANTONYMS_TABLE,
  CONFLICT_LANGUAGES_TABLE,
  CONFLICT_NEGATIONS_TABLE,
  CONFLICT_REPORT_BIGRAMS_TABLE,
  CONFLICT_SCOPE_MARKERS_TABLE,
  CONFLICT_THRESHOLDS_TABLE,
  MEASUREMENT_UNITS_TABLE,
} from "./conflict_tables.js";

interface CanonicalConflictTables {
  languages: string[];
  negations: string[];
  antonyms: [string, string][];
  report_bigrams: [string, string][];
  scope_markers: string[];
  measurement_units: string[];
  thresholds: Record<string, number>;
}

const canonical = loadData<CanonicalConflictTables>("conflict.json");

describe("generated conflict tables match conformance/conflict.json", () => {
  it("languages", () => {
    expect(CONFLICT_LANGUAGES_TABLE).toEqual(canonical.languages);
    // English only until a language has hard-negative fixtures of its own.
    expect(CONFLICT_LANGUAGES_TABLE).toEqual(["en"]);
  });

  it("negations", () => {
    expect(CONFLICT_NEGATIONS_TABLE).toEqual(canonical.negations);
    expect(CONFLICT_NEGATIONS_TABLE).toHaveLength(21);
  });

  it("antonyms", () => {
    expect(CONFLICT_ANTONYMS_TABLE).toEqual(canonical.antonyms);
    expect(CONFLICT_ANTONYMS_TABLE).toHaveLength(30);
  });

  it("report bigrams", () => {
    expect(CONFLICT_REPORT_BIGRAMS_TABLE).toEqual(canonical.report_bigrams);
    expect(CONFLICT_REPORT_BIGRAMS_TABLE).toHaveLength(11);
  });

  it("scope markers", () => {
    expect(CONFLICT_SCOPE_MARKERS_TABLE).toEqual(canonical.scope_markers);
    expect(CONFLICT_SCOPE_MARKERS_TABLE).toHaveLength(27);
  });

  it("measurement units", () => {
    expect(MEASUREMENT_UNITS_TABLE).toEqual(canonical.measurement_units);
    expect(MEASUREMENT_UNITS_TABLE).toHaveLength(73);
  });

  it("thresholds are pinned, not tunable", () => {
    expect(CONFLICT_THRESHOLDS_TABLE).toEqual(canonical.thresholds);
    // ADR-0007: relaxing max_residual to 2 buys 4pp of recall and pays 15pp of
    // false abstention, and in strict mode a false conflict is a false refusal.
    expect(CONFLICT_THRESHOLDS_TABLE.max_residual).toBe(1);
    expect(CONFLICT_THRESHOLDS_TABLE.subject_overlap).toBe(0.6);
    expect(CONFLICT_THRESHOLDS_TABLE.max_symdiff).toBe(3);
    expect(CONFLICT_THRESHOLDS_TABLE.min_content).toBe(3);
    expect(CONFLICT_THRESHOLDS_TABLE.duplicate_jaccard).toBe(0.8);
    expect(CONFLICT_THRESHOLDS_TABLE.duplicate_max_length_delta).toBe(2);
    expect(CONFLICT_THRESHOLDS_TABLE.top_k).toBe(6);
  });
});
