// `PostgresVectorStore` — pgvector + native tsvector text search (spec §6b).
// TS port of python/src/citenexus/storage/postgres_store.py.
//
// The second `VectorStore` implementation, so a team with Postgres brings their
// own database instead of adopting Lance. Semantics mirror the Lance reference:
// **one table per leaf partition** (isolation = drop a table), the same
// object-shaped EU rows, and `search` results carrying `_distance`.
//
// It ALSO implements `TextSearch`: Postgres ranks text natively with `tsvector`
// / `websearch_to_tsquery` using the `'simple'` configuration — no English
// stemming, so non-English evidence is never penalized (the same
// language-agnostic stance as the in-core BM25-lite it replaces).
//
// Dependencies stay honest: `pg` (and `pgvector`) are OPTIONAL, imported lazily
// at first connection — construction does no IO, so config-driven wiring stays
// hermetic in tests. The connection is injectable for unit tests.

import type { EuRow, SearchHit, TextHit, TextSearch, VectorStore } from "./protocols.js";

/** Column order shared by every statement (parity with Python `_COLUMNS`). */
const COLUMNS = [
  "eu_id",
  "text",
  "document_id",
  "language",
  "page",
  "checksum",
  "raw_uri",
] as const;

const IDENT = /[^a-z0-9_]+/g;

/** A safe per-leaf table name from the configured prefix + partition. */
export function tableNameFor(prefix: string, partitionSegment: string): string {
  const clean = (s: string) => s.toLowerCase().replace(IDENT, "_").replace(/^_+|_+$/g, "");
  return `${clean(prefix)}_${clean(partitionSegment)}`;
}

function vectorLiteral(vector: readonly number[]): string {
  return "[" + vector.map((x) => String(Number(x))).join(",") + "]";
}

/** True for Postgres 42P01 (undefined table) — an empty leaf, not a bug. */
function isMissingTable(error: unknown): boolean {
  const code = (error as { code?: string } | null)?.code;
  const name = (error as { name?: string } | null)?.name;
  return code === "42P01" || name === "UndefinedTable";
}

/** The minimal connection surface used here — satisfied by node-`pg`'s
 *  `Client` and `Pool` (both expose `query(text, params) => Promise<{rows}>`).
 *  Injectable so unit tests need neither `pg` nor a live server. */
export interface PgConnection {
  query(text: string, params?: unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
  end?(): Promise<void>;
}

export interface PostgresVectorStoreOptions {
  dsn: string;
  table: string;
  /** Inject a connection (tests / custom pooling). Omit to lazily open one
   *  from `dsn` via the optional `pg` dependency at first use. */
  connect?: () => PgConnection | Promise<PgConnection>;
}

/** Per-leaf EU index on Postgres: pgvector dense + tsvector lexical. */
export class PostgresVectorStore implements VectorStore, TextSearch {
  static readonly pluginVersion = "postgres-vector-v1";

  private readonly dsn: string;
  private readonly table: string;
  private readonly connect?: () => PgConnection | Promise<PgConnection>;
  private conn: PgConnection | null = null;
  private ready = false;

  constructor(opts: PostgresVectorStoreOptions) {
    // Lazy everywhere: no import, no connection until first use.
    this.dsn = opts.dsn;
    this.table = opts.table;
    this.connect = opts.connect;
  }

  /** The live connection (exposed for teardown / integration tests). */
  async connection(): Promise<PgConnection> {
    if (this.conn === null) {
      if (this.connect !== undefined) {
        this.conn = await this.connect();
      } else {
        let pg: unknown;
        // Indirect specifiers so the compiler doesn't resolve these optional
        // deps at build time — they are only needed at runtime for a live DB.
        const pgSpecifier = "pg";
        const pgvectorSpecifier = "pgvector";
        try {
          pg = await import(pgSpecifier);
        } catch (error) {
          throw new Error(
            "PostgresVectorStore needs the optional 'pg' dependency: `npm install pg pgvector`",
            { cause: error },
          );
        }
        const mod = pg as { default?: { Client: unknown }; Client?: unknown };
        const Client = (mod.default?.Client ?? mod.Client) as new (cfg: {
          connectionString: string;
        }) => PgConnection & { connect(): Promise<void> };
        const client = new Client({ connectionString: this.dsn });
        await client.connect();
        // Register pgvector's type parsers when the helper is present (optional).
        try {
          const pgvector = (await import(pgvectorSpecifier)) as {
            registerTypes?: (c: unknown) => Promise<void> | void;
            default?: { registerTypes?: (c: unknown) => Promise<void> | void };
          };
          const register = pgvector.registerTypes ?? pgvector.default?.registerTypes;
          if (register) await register(client);
        } catch {
          // pgvector helper absent — string literals + `::vector` casts still work.
        }
        this.conn = client;
      }
    }
    return this.conn;
  }

  private async ensureTable(dimension: number): Promise<void> {
    if (this.ready) return;
    const conn = await this.connection();
    await conn.query("CREATE EXTENSION IF NOT EXISTS vector");
    await conn.query(
      `CREATE TABLE IF NOT EXISTS ${this.table} (` +
        "eu_id TEXT PRIMARY KEY, " +
        `vector vector(${dimension}), ` +
        "text TEXT, document_id TEXT, language TEXT, " +
        "page INTEGER, checksum TEXT, raw_uri TEXT)",
    );
    await conn.query(
      `CREATE INDEX IF NOT EXISTS ${this.table}_fts ON ${this.table} ` +
        "USING GIN (to_tsvector('simple', coalesce(text, '')))",
    );
    this.ready = true;
  }

  /** Insert or update EU rows keyed by `eu_id` (idempotent). No-op on empty. */
  async upsert(rows: EuRow[]): Promise<void> {
    if (rows.length === 0) return;
    const first = rows[0]!;
    await this.ensureTable(first.vector.length);
    const conn = await this.connection();
    const rest = COLUMNS.slice(1); // text, document_id, language, page, checksum, raw_uri
    const assignments = ["vector", ...rest].map((c) => `${c} = EXCLUDED.${c}`).join(", ");
    // $1 eu_id, $2 vector, $3..$N the rest — mirrors Python's positional params.
    const placeholders = rest.map((_, i) => `$${i + 3}`).join(", ");
    const sql =
      `INSERT INTO ${this.table} (eu_id, vector, ${rest.join(", ")}) ` +
      `VALUES ($1, $2::vector, ${placeholders}) ` +
      `ON CONFLICT (eu_id) DO UPDATE SET ${assignments}`;
    for (const row of rows) {
      await conn.query(sql, [
        row.eu_id,
        vectorLiteral(row.vector),
        ...rest.map((c) => (row[c] ?? null) as unknown),
      ]);
    }
  }

  /** Run a SELECT; an undefined table is an empty leaf (parity with Lance). */
  private async select(sql: string, params: unknown[]): Promise<Record<string, unknown>[]> {
    const conn = await this.connection();
    try {
      const result = await conn.query(sql, params);
      return result.rows;
    } catch (error) {
      if (isMissingTable(error)) return [];
      throw error;
    }
  }

  /** Nearest rows by pgvector cosine distance (`<=>`), with `_distance`. */
  async search(vector: number[], limit = 10): Promise<SearchHit[]> {
    const rows = await this.select(
      `SELECT ${COLUMNS.join(", ")}, vector <=> $1::vector AS _distance ` +
        `FROM ${this.table} ORDER BY _distance LIMIT $2`,
      [vectorLiteral(vector), limit],
    );
    return rows.map((r) => ({ ...r, _distance: Number(r._distance) }) as SearchHit);
  }

  /** Native lexical ranking via tsvector ('simple' config — no stemming). */
  async searchText(query: string, limit = 10): Promise<TextHit[]> {
    const rows = await this.select(
      `SELECT ${COLUMNS.join(", ")}, ` +
        "ts_rank(to_tsvector('simple', coalesce(text, '')), " +
        "websearch_to_tsquery('simple', $1)) AS _text_score " +
        `FROM ${this.table} ` +
        "WHERE to_tsvector('simple', coalesce(text, '')) @@ " +
        "websearch_to_tsquery('simple', $1) " +
        "ORDER BY _text_score DESC LIMIT $2",
      [query, limit],
    );
    return rows.map((r) => ({ ...r, _text_score: Number(r._text_score) }) as TextHit);
  }

  /** All rows in this leaf — the corpus for lexical/structure signals. */
  async scan(limit: number | null = null): Promise<Record<string, unknown>[]> {
    let sql = `SELECT ${COLUMNS.join(", ")} FROM ${this.table}`;
    const params: unknown[] = [];
    if (limit !== null && limit !== undefined) {
      sql += " LIMIT $1";
      params.push(limit);
    }
    return this.select(sql, params);
  }
}

/** The text-search half of the Postgres backend pairing.
 *
 *  Postgres ranks text natively (`tsvector`), so this delegates to the store's
 *  `searchText` — sharing its connection and leaf table. Named so each backend
 *  reads as a (vector, text) pair: `PostgresVectorStore` + `PostgresTextSearch`,
 *  mirroring the Lance store + its BM25-lite text search. */
export class PostgresTextSearch implements TextSearch {
  static readonly pluginVersion = "postgres-text-search-v1";

  constructor(private readonly store: PostgresVectorStore) {}

  searchText(query: string, limit = 10): Promise<TextHit[]> {
    return this.store.searchText(query, limit);
  }
}
