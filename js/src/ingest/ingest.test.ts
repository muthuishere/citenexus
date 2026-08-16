// Ingest orchestrator test — exercises the full extract -> chunk -> embed ->
// store path, with the real Rust core (extract + Lance store) and a
// deterministic fake embedder. Requires the cdylib:
//   cd rust && cargo build --release

import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Store } from "../core/core.js";
import { FakeEmbedding, EMBED_DIM } from "../fakes/fakes.js";
import { ingest } from "./ingest.js";

describe("ingest orchestrator", () => {
  const tmpDirs: string[] = [];
  afterEach(() => {
    for (const d of tmpDirs.splice(0)) rmSync(d, { recursive: true, force: true });
  });

  it("extracts, chunks, embeds and stores retrievable evidence units", async () => {
    const dir = mkdtempSync(join(tmpdir(), "citenexus-ingest-"));
    tmpDirs.push(dir);
    const store = Store.open(dir);
    const fake = new FakeEmbedding();
    const embed = (text: string): number[] => fake.embed(text);

    try {
      const text = "The cat sat on the mat.\n\nThe dog ran in the park.";
      const result = await ingest(store, new TextEncoder().encode(text), "plain", "docX", embed);

      expect(result.documentId).toBe("docX");
      expect(result.unitCount).toBeGreaterThan(0);
      expect(result.euIds).toHaveLength(result.unitCount);
      // eu_id shape: {document}::{order}::{chunk}
      expect(result.euIds[0]).toMatch(/^docX::\d+::\d+$/);

      // Everything ingested is scannable.
      const rows = store.scan();
      expect(rows).toHaveLength(result.unitCount);
      const dims = rows.map((r) => (r["vector"] as number[]).length);
      expect(new Set(dims)).toEqual(new Set([EMBED_DIM]));

      // The stored vectors are the ones we embedded, so the same query vector
      // retrieves its own unit at distance 0.
      const first = rows[0]!;
      const hits = store.search(first["vector"] as number[], 1);
      expect(hits).toHaveLength(1);
      expect(hits[0]!["eu_id"]).toBe(first["eu_id"]);

      // Re-ingesting the same document is idempotent (merge on eu_id).
      const again = await ingest(store, new TextEncoder().encode(text), "plain", "docX", embed);
      expect(again.unitCount).toBe(result.unitCount);
      expect(store.scan()).toHaveLength(result.unitCount);
    } finally {
      store.close();
    }
  });
  it("refuses — and writes NOTHING — when the model call fails", async () => {
    // The regression for ADR-0014 R2. With the old synchronous seam a failing
    // embedder had nowhere to say so; the rejection was never awaited and
    // `ingest()` returned a healthy-looking result over a poisoned corpus.
    const dir = mkdtempSync(join(tmpdir(), "citenexus-ingest-fail-"));
    tmpDirs.push(dir);
    const store = Store.open(dir);
    const fake = new FakeEmbedding();
    let calls = 0;
    const embed = async (text: string): Promise<number[]> => {
      calls += 1;
      if (calls === 2) throw new Error("model call timed out after 30s");
      return fake.embed(text);
    };

    try {
      const bytes = new TextEncoder().encode(
        "The employee may disclose the defect.\n\nThe employee may NOT disclose the defect.",
      );
      await expect(ingest(store, bytes, "plain", "docFAIL", embed)).rejects.toThrow(/timed out/);
      // Fail-closed and all-or-nothing: not one row landed.
      expect(store.scan()).toHaveLength(0);
    } finally {
      store.close();
    }
  });

  it("refuses the zero vector even when the embedder reports success", async () => {
    const dir = mkdtempSync(join(tmpdir(), "citenexus-ingest-zero-"));
    tmpDirs.push(dir);
    const store = Store.open(dir);
    const embed = (): number[] => new Array<number>(EMBED_DIM).fill(0);

    try {
      const bytes = new TextEncoder().encode("The cat sat on the mat.");
      await expect(ingest(store, bytes, "plain", "docZERO", embed)).rejects.toThrow(/zero vector/);
      expect(store.scan()).toHaveLength(0);
    } finally {
      store.close();
    }
  });
});
