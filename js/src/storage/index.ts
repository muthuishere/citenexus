// Pluggable vector databases behind two protocols — `VectorStore` (dense) and
// `TextSearch` (lexical) — with each backend contributing a (vector, text) pair:
//
// - **Lance** (recommended, zero infra, S3-native): the native `Store`
//   (core/core.ts) + in-core BM25-lite over `scan()`.
// - **Postgres** (bring your own DB): `PostgresVectorStore` + `PostgresTextSearch`
//   (pgvector dense + native `tsvector` text).
// - **Yours**: implement the protocols and inject.
//
// TS port of python/src/citenexus/storage/__init__.py (index-layer subset).

export type {
  EuRow,
  SearchHit,
  TextHit,
  TextSearch,
  VectorStore,
} from "./protocols.js";
export {
  PostgresTextSearch,
  PostgresVectorStore,
  tableNameFor,
  type PgConnection,
  type PostgresVectorStoreOptions,
} from "./postgres.js";
