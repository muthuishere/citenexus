// The vector-store and text-search seams (spec §6b, §10) — TS port of
// python/src/citenexus/storage/protocols.py.
//
// CiteNexus's retrievable index lives behind two protocols:
//
// - `VectorStore` — the per-leaf index every consumer goes through with exactly
//   three methods (`upsert` / `search` / `scan`). The native Lance `Store`
//   (core/core.ts, Rust twin of Python's LanceVectorStore) is the zero-infra,
//   S3-native REFERENCE backend and stays the default; `PostgresVectorStore`
//   (pgvector) lets a team bring their existing Postgres instead.
// - `TextSearch` — OPTIONAL native lexical search. A backend that can rank text
//   itself (Postgres `tsvector`) implements it and the lexical signal delegates;
//   a backend that can't (Lance) simply doesn't, and the in-core BM25-lite over
//   `scan()` is used.
//
// Rows are plain objects with the EU keys the ingest pipeline writes: `eu_id`,
// `vector`, `text`, `document_id`, `language`, `page`, `checksum`, `raw_uri`.
// `search` results additionally carry `_distance`; `search_text` results carry
// `_text_score`.
//
// NOTE ON ASYNC: the Python protocols are synchronous, but a real database
// client in Node is inherently async. The TS protocols therefore return
// Promises. Method NAMES and SEMANTICS mirror Python exactly (see
// postgres.ts); the native Lance `Store` remains the synchronous FFI peer.

/** One evidence-unit row keyed by `eu_id`; `vector` is a dense float array. */
export interface EuRow {
  eu_id: string;
  vector: number[];
  text?: string | null;
  document_id?: string | null;
  language?: string | null;
  page?: number | null;
  checksum?: string | null;
  raw_uri?: string | null;
  [column: string]: unknown;
}

/** An `EuRow` as returned by `search` — carries the pgvector cosine distance. */
export type SearchHit = Record<string, unknown> & { _distance: number };

/** An `EuRow` as returned by `search_text` — carries the native text score. */
export type TextHit = Record<string, unknown> & { _text_score: number };

/** The per-leaf retrievable index — the seam all consumers go through. */
export interface VectorStore {
  /** Insert or update EU rows keyed by `eu_id` (idempotent). No-op on empty. */
  upsert(rows: EuRow[]): Promise<void>;

  /** Nearest rows to `vector` (each with `_distance`); [] when empty. */
  search(vector: number[], limit?: number): Promise<SearchHit[]>;

  /** All rows in this leaf — the corpus for lexical/structure signals. */
  scan(limit?: number | null): Promise<Record<string, unknown>[]>;

  /** Remove every row carrying `documentId` — the row-level inverse of an
   *  ingest (document-revoke). A no-op when nothing matches or the leaf has no
   *  table yet. Mirrors python `VectorStore.delete_document`. */
  deleteDocument(documentId: string): Promise<void>;
}

/** Native lexical ranking, when the backend can do it itself. */
export interface TextSearch {
  /** Rows ranked by the backend's own text relevance (each with a score under
   *  `_text_score`); [] when nothing matches. */
  searchText(query: string, limit?: number): Promise<TextHit[]>;
}
