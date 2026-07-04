// FFI binding tests — these EXERCISE the real Rust core (citenexus-core) through
// koffi. They require the cdylib to be built first:
//   cd rust && cargo build --release
// They are intentionally not part of `tsc` type-checking of the pure port; the
// module is isolated so consumers without the native library are unaffected.

import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

import { version, extract, detect, Store } from "./core.js";

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
