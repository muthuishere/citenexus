import { describe, it, expect } from "vitest";
import { createConnection } from "node:net";
import { PostgresVectorStore, tableNameFor } from "./postgres.js";
import type { EuRow } from "./protocols.js";

// Opt-in Postgres/pgvector round-trip — TS port of
// python/tests/storage/test_integration_postgres.py. Gated exactly like Python:
// skips unless `pg` is installed AND Postgres answers on the compose port.
//   upsert → dense search (pgvector cosine) → native text search (tsvector)
//   → scan → idempotent re-upsert.
//
// Run against the compose `postgres` profile (default localhost:15432), e.g.:
//   CITENEXUS_PG_DSN=postgresql://citenexus:citenexus@localhost:15432/citenexus npm test

const DSN =
  process.env.CITENEXUS_PG_DSN ?? "postgresql://citenexus:citenexus@localhost:15432/citenexus";
const PORT = Number(process.env.CITENEXUS_PG_PORT ?? "15432");

async function pgReachable(): Promise<boolean> {
  try {
    const pgSpecifier = "pg";
    await import(pgSpecifier);
  } catch {
    return false;
  }
  return new Promise((resolve) => {
    const sock = createConnection({ host: "localhost", port: PORT });
    const done = (ok: boolean) => {
      sock.destroy();
      resolve(ok);
    };
    sock.setTimeout(2000);
    sock.once("connect", () => done(true));
    sock.once("timeout", () => done(false));
    sock.once("error", () => done(false));
  });
}

const live = await pgReachable();

describe.skipIf(!live)("PostgresVectorStore round-trip (live pg)", () => {
  it("upsert → cosine search → tsvector text search → scan → idempotent re-upsert", async () => {
    const suffix = Math.random().toString(16).slice(2, 10);
    const table = tableNameFor("citenexus_it", `workspace=${suffix}`);
    const store = new PostgresVectorStore({ dsn: DSN, table });
    const rows: EuRow[] = [
      { eu_id: "nda::0", vector: [1, 0, 0], text: "The employee shall not disclose confidential information.", document_id: "nda", language: "en", page: 1, checksum: "abc", raw_uri: "raw/abc" },
      { eu_id: "cats::0", vector: [0, 1, 0], text: "Cats are small domestic animals.", document_id: "cats", language: "en", page: -1, checksum: "def", raw_uri: "raw/def" },
    ];
    try {
      await store.upsert(rows);

      const hits = await store.search([1, 0, 0], 1);
      expect(hits[0]!.eu_id).toBe("nda::0");
      expect(hits[0]!._distance).toBeLessThan(0.01);

      const textHits = await store.searchText("confidential disclose", 2);
      expect(textHits[0]!.eu_id).toBe("nda::0");

      expect((await store.scan()).length).toBe(2);
      await store.upsert(rows); // idempotent
      expect((await store.scan()).length).toBe(2);
    } finally {
      const conn = await store.connection();
      await conn.query(`DROP TABLE IF EXISTS ${table}`);
      if (conn.end) await conn.end();
    }
  });
});
