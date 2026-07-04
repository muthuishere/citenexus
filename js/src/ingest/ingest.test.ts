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

  it("extracts, chunks, embeds and stores retrievable evidence units", () => {
    const dir = mkdtempSync(join(tmpdir(), "citenexus-ingest-"));
    tmpDirs.push(dir);
    const store = Store.open(dir);
    const fake = new FakeEmbedding();
    const embed = (text: string): number[] => fake.embed(text);

    try {
      const text = "The cat sat on the mat.\n\nThe dog ran in the park.";
      const result = ingest(store, new TextEncoder().encode(text), "plain", "docX", embed);

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
      const again = ingest(store, new TextEncoder().encode(text), "plain", "docX", embed);
      expect(again.unitCount).toBe(result.unitCount);
      expect(store.scan()).toHaveLength(result.unitCount);
    } finally {
      store.close();
    }
  });
});
