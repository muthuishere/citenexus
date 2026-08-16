// Drift guard: the bundled tables must equal the canonical conformance files.
//
// Runtime code imports the GENERATED module (so the published package is
// self-contained); the tests read conformance/ directly. If the two disagree,
// someone edited the generated file by hand or forgot to regenerate — this
// turns that into a loud failure instead of a silent divergence between the
// published package and the cross-language contract.
import { describe, expect, it } from "vitest";

import { loadData } from "../conform/fixtures.js";
import { loadCase } from "../conform/fixtures.js";
import {
  CONTINUOUS_SCRIPTS_TABLE,
  POLARITY_TABLE,
  SUPPORTED_SCRIPTS_TABLE,
  SEGMENTATION_TABLE,
  STOPWORDS_TABLE,
  TOKENIZER_VERSION_TABLE,
} from "./tables.js";

describe("generated tables match conformance/", () => {
  it("stopwords", () => {
    expect(STOPWORDS_TABLE).toEqual(loadData<string[]>("stopwords.json"));
  });

  it("polarity", () => {
    expect(POLARITY_TABLE).toEqual(loadData("polarity.json"));
  });

  it("segmentation", () => {
    expect(SEGMENTATION_TABLE).toEqual(loadData("segmentation.json"));
  });

  it("script tables (ADR-0011)", () => {
    const fixture = loadCase<{
      tokenizer_version: number;
      supported_scripts: string[];
      continuous_scripts: string[];
    }>("tokenize_v2.json");
    expect(SUPPORTED_SCRIPTS_TABLE).toEqual(fixture.supported_scripts);
    expect(CONTINUOUS_SCRIPTS_TABLE).toEqual(fixture.continuous_scripts);
    expect(TOKENIZER_VERSION_TABLE).toEqual(fixture.tokenizer_version);
  });

  it("claims only languages that have a golden fixture", () => {
    expect(POLARITY_TABLE.languages).toEqual(["en"]);
  });
});
