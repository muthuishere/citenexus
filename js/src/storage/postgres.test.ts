import { describe, it, expect } from "vitest";
import {
  PostgresVectorStore,
  PostgresTextSearch,
  tableNameFor,
  type PgConnection,
} from "./postgres.js";
import type { EuRow } from "./protocols.js";

// Hermetic port of python/tests/storage/test_postgres_store.py: a fake
// connection records every statement and returns canned rows for SELECTs, so
// the SQL contract (dimension inference, ON CONFLICT, `<=>`, tsvector) is proven
// without `pg` or a live server. The real round-trip is postgres.integration.test.ts.

class FakeConnection implements PgConnection {
  statements: Array<{ sql: string; params?: unknown[] }> = [];
  commitsSeen = 0;
  constructor(private readonly selectRows: Record<string, unknown>[] = []) {}

  query(text: string, params?: unknown[]): Promise<{ rows: Record<string, unknown>[] }> {
    const sql = text.split(/\s+/).join(" ").trim();
    this.statements.push({ sql, params });
    const rows = sql.toUpperCase().startsWith("SELECT") ? this.selectRows : [];
    return Promise.resolve({ rows });
  }
}

const ROW: EuRow = {
  eu_id: "doc::0",
  vector: [0.1, 0.2, 0.3],
  text: "The employee shall not disclose.",
  document_id: "doc",
  language: "en",
  page: 1,
  checksum: "abc",
  raw_uri: "raw/abc",
};

const store = (conn: PgConnection) =>
  new PostgresVectorStore({ dsn: "postgresql://ignored", table: "citenexus_ws_default", connect: () => conn });

const blob = (conn: FakeConnection) => conn.statements.map((s) => s.sql).join(" ");

describe("PostgresVectorStore (hermetic)", () => {
  it("upsert creates the table with the vector dimension inferred from the first row", async () => {
    const conn = new FakeConnection();
    await store(conn).upsert([ROW]);
    const sql = blob(conn);
    expect(sql).toContain("CREATE EXTENSION IF NOT EXISTS vector");
    expect(sql).toContain("vector(3)");
    expect(sql).toContain("ON CONFLICT (eu_id) DO UPDATE");
  });

  it("upsert on empty is a no-op (no statements)", async () => {
    const conn = new FakeConnection();
    await store(conn).upsert([]);
    expect(conn.statements).toEqual([]);
  });

  it("upsert passes eu_id + vector literal + the remaining columns positionally", async () => {
    const conn = new FakeConnection();
    await store(conn).upsert([ROW]);
    const insert = conn.statements.find((s) => s.sql.startsWith("INSERT"))!;
    expect(insert.params).toEqual([
      "doc::0",
      "[0.1,0.2,0.3]",
      "The employee shall not disclose.",
      "doc",
      "en",
      1,
      "abc",
      "raw/abc",
    ]);
  });

  it("search orders by cosine distance (<=>) and maps _distance", async () => {
    const conn = new FakeConnection([
      { eu_id: "doc::0", text: "The employee shall not disclose.", document_id: "doc", language: "en", page: 1, checksum: "abc", raw_uri: "raw/abc", _distance: 0.12 },
    ]);
    const hits = await store(conn).search([0.1, 0.2, 0.3], 5);
    const sql = conn.statements.at(-1)!.sql;
    expect(sql).toContain("<=>");
    expect(sql).toContain("LIMIT");
    expect(hits[0]!.eu_id).toBe("doc::0");
    expect(hits[0]!._distance).toBe(0.12);
    expect(hits[0]!.page).toBe(1);
  });

  it("searchText uses native tsvector ranking with the 'simple' config", async () => {
    const conn = new FakeConnection([
      { eu_id: "doc::0", text: "The employee shall not disclose.", document_id: "doc", language: "en", page: 1, checksum: "abc", raw_uri: "raw/abc", _text_score: 0.61 },
    ]);
    const hits = await store(conn).searchText("disclose employee", 5);
    const sql = conn.statements.at(-1)!.sql;
    expect(sql).toContain("websearch_to_tsquery");
    expect(sql).toContain("'simple'");
    expect(hits[0]!._text_score).toBe(0.61);
  });

  it("scan returns all rows as objects", async () => {
    const conn = new FakeConnection([
      { eu_id: "doc::0", text: "text a", document_id: "doc", language: "en", page: -1, checksum: "abc", raw_uri: "raw/abc" },
    ]);
    const rows = await store(conn).scan();
    expect(rows[0]!.eu_id).toBe("doc::0");
    expect(rows[0]!.text).toBe("text a");
    expect(rows[0]!.page).toBe(-1);
  });

  it("a SELECT against a missing table (42P01) is an empty leaf, not an error", async () => {
    const conn: PgConnection = {
      query() {
        return Promise.reject(Object.assign(new Error("relation does not exist"), { code: "42P01" }));
      },
    };
    expect(await store(conn).search([0.1, 0.2, 0.3])).toEqual([]);
    expect(await store(conn).scan()).toEqual([]);
  });

  it("PostgresTextSearch delegates to the store's searchText", async () => {
    const conn = new FakeConnection([
      { eu_id: "doc::0", text: "x", document_id: "doc", language: "en", page: 1, checksum: "abc", raw_uri: "raw/abc", _text_score: 0.42 },
    ]);
    const s = store(conn);
    const hits = await new PostgresTextSearch(s).searchText("x", 3);
    expect(hits[0]!._text_score).toBe(0.42);
  });
});

describe("tableNameFor", () => {
  it("sanitizes prefix + partition into a safe identifier", () => {
    expect(tableNameFor("citenexus", "workspace=Acme Corp")).toBe("citenexus_workspace_acme_corp");
    expect(tableNameFor("CiteNexus_IT", "a/b::c")).toBe("citenexus_it_a_b_c");
  });
});
