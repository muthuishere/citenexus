// FFI binding tests — these EXERCISE the real Rust core (citenexus-core) through
// koffi. They require the cdylib to be built first:
//   cd rust && cargo build --release
// They are intentionally not part of `tsc` type-checking of the pure port; the
// module is isolated so consumers without the native library are unaffected.

import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, rmSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

import { version, extract, toMarkdown, detect, Store } from "./core.js";

const HERE = dirname(fileURLToPath(import.meta.url));
// src/core -> ../../../assets/models/lid.176.bin
const MODEL_PATH =
  process.env.CITENEXUS_LID176_MODEL ??
  resolve(HERE, "..", "..", "..", "assets", "models", "lid.176.bin");

describe("citenexus-core FFI", () => {
  const tmpDirs: string[] = [];

  afterEach(() => {
    for (const d of tmpDirs.splice(0)) {
      rmSync(d, { recursive: true, force: true });
    }
  });

  it("version() returns a non-empty semver from the Rust core", () => {
    const v = version();
    expect(v).toBeTruthy();
    expect(v).toMatch(/^\d+\.\d+\.\d+/);
  });

  it("extract() of a plain doc yields blocks", () => {
    const doc = extract(
      new TextEncoder().encode("Hello CiteNexus.\n\nSecond paragraph here."),
      "plain",
      "doc1",
    );
    expect(doc.document_id).toBe("doc1");
    expect(doc.blocks.length).toBeGreaterThan(0);
    expect(doc.blocks[0]!.text.length).toBeGreaterThan(0);
  });

  it("toMarkdown() converts the xlsx fixture sheet by sheet", () => {
    // src/core -> ../../../conformance/fixtures/sample.xlsx
    const fixture = resolve(HERE, "..", "..", "..", "conformance", "fixtures", "sample.xlsx");
    const markdown = toMarkdown(readFileSync(fixture), "xlsx");
    // Sheets emit as GFM pipe tables (the shipped emit-markdown behavior).
    expect(markdown).toContain("# People");
    expect(markdown).toContain("| name | age | active |");
    expect(markdown).toContain("| ada | 36 | true |");
    expect(markdown).toContain("# Scores");
    expect(markdown.endsWith("\n")).toBe(true);
  });

  it("toMarkdown() throws the core-reported error on invalid bytes", () => {
    expect(() => toMarkdown(new TextEncoder().encode("not a workbook"), "xlsx")).toThrow(
      /citenexus-core/,
    );
  });

  it("Store round-trips upsert -> scan -> search against a temp dir", () => {
    const dir = mkdtempSync(join(tmpdir(), "citenexus-store-"));
    tmpDirs.push(dir);
    const store = Store.open(dir);
    try {
      store.upsert([
        { eu_id: "a", text: "hello", vector: [1, 0, 0, 0] },
        { eu_id: "b", text: "world", vector: [0, 1, 0, 0] },
      ]);

      const all = store.scan();
      expect(all).toHaveLength(2);
      expect(all.map((r) => r["eu_id"]).sort()).toEqual(["a", "b"]);

      const hits = store.search([1, 0, 0, 0], 1);
      expect(hits).toHaveLength(1);
      expect(hits[0]!["eu_id"]).toBe("a");
      expect(hits[0]!).toHaveProperty("_distance");

      // Idempotent re-upsert keeps the row count stable.
      store.upsert([{ eu_id: "a", text: "hello again", vector: [1, 0, 0, 0] }]);
      expect(store.scan()).toHaveLength(2);
    } finally {
      store.close();
    }
  });

  it("Store.deleteDocument removes only that document's rows (document-revoke)", () => {
    const dir = mkdtempSync(join(tmpdir(), "citenexus-delete-"));
    tmpDirs.push(dir);
    const store = Store.open(dir);
    try {
      // Delete before any table exists is a no-op.
      store.deleteDocument("nda");

      store.upsert([
        { eu_id: "nda::0", text: "secret", vector: [1, 0, 0, 0], document_id: "nda" },
        { eu_id: "leave::0", text: "leave", vector: [0, 1, 0, 0], document_id: "leave" },
      ]);

      store.deleteDocument("nda");
      const remaining = store.scan();
      expect(remaining).toHaveLength(1);
      expect(remaining[0]!["document_id"]).toBe("leave");

      // Unknown id is a no-op.
      store.deleteDocument("ghost");
      expect(store.scan()).toHaveLength(1);
    } finally {
      store.close();
    }
  });

  it("detect() identifies language (skips if lid.176 model absent)", () => {
    if (!existsSync(MODEL_PATH)) {
      // The 126MB model is a vendored asset; skip cleanly when not present.
      console.warn(`skipping detect: model not found at ${MODEL_PATH}`);
      return;
    }
    const en = detect(MODEL_PATH, "The quick brown fox jumps over the lazy dog.");
    expect(en.language).toBe("en");
    expect(en.confidence).toBeGreaterThan(0);

    const fr = detect(MODEL_PATH, "Bonjour le monde, comment allez-vous aujourd'hui ?");
    expect(fr.language).toBe("fr");
  });
});

// ---- the PDF model contract (ADR-0017; docs/pdf-model-contract.md) ---------

import {
  pdfUnits,
  pdfUnitsJson,
  pdfPrepare,
  pdfAssemble,
  pdfAssembleJson,
  ooxmlUnits,
  citableText,
  type PdfResponse,
} from "./core.js";

const PDF_DATA = resolve(HERE, "..", "..", "..", "rust", "tests", "data");
const PDF_OPTS = { language: "nl", model_tables: true };

/** The PDF tests need the core built with --features pdf and libpdfium
 *  loadable (PDFIUM_DYNAMIC_LIB_PATH); skip with a message otherwise. */
function pdfReady(pdf: Uint8Array): boolean {
  try {
    pdfUnits(pdf, { language: "nl" });
    return true;
  } catch (err) {
    const msg = String(err);
    if (msg.includes("`pdf` feature") || msg.includes("libpdfium")) {
      console.warn(`skipping PDF core tests: ${msg.slice(0, 120)}`);
      return false;
    }
    throw err;
  }
}

describe("citenexus-core PDF contract", () => {
  const pdf = new Uint8Array(readFileSync(join(PDF_DATA, "pdf", "assemble-mixed.pdf")));
  const responsesJson = readFileSync(join(PDF_DATA, "pdf", "assemble-mixed.responses.json"), "utf8");
  const golden = readFileSync(join(PDF_DATA, "pdf", "assemble-mixed.golden.json"), "utf8");

  it("assemble reproduces the Rust golden byte for byte", () => {
    if (!pdfReady(pdf)) return;
    expect(pdfAssembleJson(pdf, responsesJson, PDF_OPTS)).toBe(golden);
  });

  it("prepare -> fulfil -> assemble, typed", () => {
    if (!pdfReady(pdf)) return;
    const prep = pdfPrepare(pdf, PDF_OPTS);
    expect(prep.requests.map((r) => r.id)).toEqual([
      "p1:table0",
      "p2:page:v1",
      "p2:page:v2",
      "p3:img0:v1",
      "p3:img0:v2",
    ]);
    expect(prep.requests[0]!.variant).toBeNull();
    expect(prep.requests.slice(1, 3).map((r) => r.variant)).toEqual([1, 2]);
    const answers = JSON.parse(responsesJson) as PdfResponse[];
    const out = pdfAssemble(pdf, answers, PDF_OPTS);
    expect(out.document.responses_applied).toBe(5);
    const tables = out.units.filter((u) => u.kind === "table");
    expect(tables).toHaveLength(1);
    expect(tables[0]!.provenance.table_source).toBe("ruled");
    const scan = out.units.filter((u) => u.page === 2 && u.provenance.vision_transcribed);
    expect(scan).toHaveLength(1);
    expect(scan[0]!.provenance.vision_disputed).toBe(true);
    const cite = citableText(scan[0]!.markdown);
    expect(cite).toContain("Diner 1.250,00 vooraf betaald");
    expect(cite).not.toContain("geen");
  });

  it("units is assemble without responses, byte for byte", () => {
    if (!pdfReady(pdf)) return;
    expect(pdfAssembleJson(pdf, "[]", PDF_OPTS)).toBe(pdfUnitsJson(pdf, PDF_OPTS));
  });

  it("ooxmlUnits reads a DOCX heading and table", () => {
    const docx = new Uint8Array(readFileSync(join(PDF_DATA, "ooxml", "sample.docx")));
    const units = ooxmlUnits(docx, "docx");
    expect(units[0]!.kind).toBe("heading");
    expect(units[0]!.markdown).toBe("# Vergoedingen");
    const table = units.find((u) => u.kind === "table");
    expect(table?.markdown).toContain("| Reiskosten | 7.000,00 |");
    expect(table?.provenance.route).toBe("ooxml");
  });

  it("citableText strips disputed text and image descriptions", () => {
    const md =
      "Diner 1.250,00 vooraf betaald.\n<!-- vision_disputed\nv1: Hotel 5.100,00 per jaar.\nv2: Hotel 5.100,00 geen per jaar.\n-->\nArtikel I.3.";
    expect(citableText(md)).toBe("Diner 1.250,00 vooraf betaald.\nArtikel I.3.");
    expect(citableText("<!-- image_description\nEen logo\n-->")).toBe("");
  });
});
