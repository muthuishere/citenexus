// PostgresVectorStore — pgvector + native tsvector text search (spec §6b).
//
// The second VectorStore implementation, so a team with Postgres brings their
// own database instead of adopting LanceDB. Semantics mirror the LanceDB
// reference and the Python PostgresVectorStore byte-for-byte: one table per leaf
// partition (isolation = drop a table), the same map-shaped EU rows, and Search
// results carrying "_distance".
//
// It ALSO implements TextSearch: Postgres ranks text natively with tsvector /
// websearch_to_tsquery using the 'simple' configuration — no English stemming,
// so non-English evidence is never penalized (the same language-agnostic stance
// as the in-core BM25-lite it replaces).
//
// Connection is lazy: no connection until first use — construction does no IO,
// so config-driven wiring stays hermetic in tests. The connection is injectable
// (Connect) for unit tests, mirroring the Python `connect=` hook.
package storage

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// PGConn is the minimal connection surface PostgresVectorStore needs — satisfied
// by *pgx.Conn. Injectable so tests can supply a fake.
type PGConn interface {
	Exec(ctx context.Context, sql string, args ...any) (pgconn.CommandTag, error)
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	Close(ctx context.Context) error
}

// PostgresVectorStore is a per-leaf EU index on Postgres: pgvector dense +
// tsvector lexical. Mirrors python storage.postgres_store.PostgresVectorStore.
type PostgresVectorStore struct {
	// PluginVersion mirrors the Python plugin_version tag.
	dsn     string
	table   string
	connect func() (PGConn, error)
	conn    PGConn
	ready   bool
}

// PluginVersion mirrors PostgresVectorStore.plugin_version in Python.
const PluginVersion = "postgres-vector-v1"

// NewPostgresVectorStore builds a lazy store. It does NO IO: the connection is
// opened on first use. Pass a non-nil connect to inject a connection (tests);
// otherwise dsn is dialed with pgx on first use. Mirrors the Python __init__.
func NewPostgresVectorStore(dsn, table string, connect func() (PGConn, error)) *PostgresVectorStore {
	return &PostgresVectorStore{dsn: dsn, table: table, connect: connect}
}

func (s *PostgresVectorStore) connection(ctx context.Context) (PGConn, error) {
	if s.conn == nil {
		if s.connect != nil {
			c, err := s.connect()
			if err != nil {
				return nil, err
			}
			s.conn = c
		} else {
			c, err := pgx.Connect(ctx, s.dsn)
			if err != nil {
				return nil, err
			}
			s.conn = c
		}
	}
	return s.conn, nil
}

// Close closes the underlying connection if one was opened.
func (s *PostgresVectorStore) Close(ctx context.Context) error {
	if s.conn != nil {
		err := s.conn.Close(ctx)
		s.conn = nil
		s.ready = false
		return err
	}
	return nil
}

func (s *PostgresVectorStore) ensureTable(ctx context.Context, dimension int) error {
	if s.ready {
		return nil
	}
	conn, err := s.connection(ctx)
	if err != nil {
		return err
	}
	if _, err := conn.Exec(ctx, "CREATE EXTENSION IF NOT EXISTS vector"); err != nil {
		return err
	}
	if _, err := conn.Exec(ctx, fmt.Sprintf(
		"CREATE TABLE IF NOT EXISTS %s ("+
			"eu_id TEXT PRIMARY KEY, "+
			"vector vector(%d), "+
			"text TEXT, document_id TEXT, language TEXT, "+
			"page INTEGER, checksum TEXT, raw_uri TEXT)",
		s.table, dimension)); err != nil {
		return err
	}
	if _, err := conn.Exec(ctx, fmt.Sprintf(
		"CREATE INDEX IF NOT EXISTS %s_fts ON %s "+
			"USING GIN (to_tsvector('simple', coalesce(text, '')))",
		s.table, s.table)); err != nil {
		return err
	}
	s.ready = true
	return nil
}

// Upsert inserts or updates EU rows keyed by eu_id (idempotent). Ensures the
// leaf table exists sized to the first row's vector dimension, like Python.
func (s *PostgresVectorStore) Upsert(rows []Row) error {
	if len(rows) == 0 {
		return nil
	}
	ctx := context.Background()
	vec, err := rowVector(rows[0])
	if err != nil {
		return err
	}
	if err := s.ensureTable(ctx, len(vec)); err != nil {
		return err
	}
	conn, err := s.connection(ctx)
	if err != nil {
		return err
	}

	payload := euColumns[1:] // text, document_id, language, page, checksum, raw_uri
	assignments := []string{"vector = EXCLUDED.vector"}
	for _, c := range payload {
		assignments = append(assignments, fmt.Sprintf("%s = EXCLUDED.%s", c, c))
	}
	// placeholders: $1 eu_id, $2::vector, $3.. payload
	placeholders := []string{"$1", "$2::vector"}
	for i := range payload {
		placeholders = append(placeholders, fmt.Sprintf("$%d", i+3))
	}
	sql := fmt.Sprintf(
		"INSERT INTO %s (eu_id, vector, %s) VALUES (%s) "+
			"ON CONFLICT (eu_id) DO UPDATE SET %s",
		s.table, strings.Join(payload, ", "),
		strings.Join(placeholders, ", "),
		strings.Join(assignments, ", "))

	for _, row := range rows {
		vec, err := rowVector(row)
		if err != nil {
			return err
		}
		args := []any{row["eu_id"], vectorLiteral(vec)}
		for _, c := range payload {
			args = append(args, row[c])
		}
		if _, err := conn.Exec(ctx, sql, args...); err != nil {
			return err
		}
	}
	return nil
}

// isMissingTable reports Postgres 42P01 (undefined table) — an empty leaf, not a
// bug. Mirrors _is_missing_table() in Python.
func isMissingTable(err error) bool {
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		return pgErr.Code == "42P01"
	}
	return false
}

// selectRows runs a SELECT; an undefined table is an empty leaf (parity with
// LanceDB). Returns rows as [][]any in column order. Mirrors _select().
func (s *PostgresVectorStore) selectRows(ctx context.Context, sql string, args ...any) ([][]any, error) {
	conn, err := s.connection(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := conn.Query(ctx, sql, args...)
	if err != nil {
		if isMissingTable(err) {
			return nil, nil
		}
		return nil, err
	}
	defer rows.Close()
	var out [][]any
	for rows.Next() {
		vals, err := rows.Values()
		if err != nil {
			return nil, err
		}
		out = append(out, vals)
	}
	if err := rows.Err(); err != nil {
		if isMissingTable(err) {
			return nil, nil
		}
		return nil, err
	}
	return out, nil
}

// Search returns nearest rows by pgvector cosine distance (<=>), with
// "_distance". Mirrors PostgresVectorStore.search.
func (s *PostgresVectorStore) Search(vector []float64, limit int) ([]Row, error) {
	ctx := context.Background()
	cols := strings.Join(euColumns, ", ")
	sql := fmt.Sprintf(
		"SELECT %s, vector <=> $1::vector AS _distance FROM %s ORDER BY _distance LIMIT $2",
		cols, s.table)
	raw, err := s.selectRows(ctx, sql, vectorLiteral(vector), limit)
	if err != nil {
		return nil, err
	}
	return zipRows(raw, append(append([]string{}, euColumns...), "_distance")), nil
}

// SearchText returns rows ranked by native tsvector ('simple' config — no
// stemming), with "_text_score". Mirrors PostgresVectorStore.search_text.
func (s *PostgresVectorStore) SearchText(query string, limit int) ([]Row, error) {
	ctx := context.Background()
	cols := strings.Join(euColumns, ", ")
	sql := fmt.Sprintf(
		"SELECT %s, "+
			"ts_rank(to_tsvector('simple', coalesce(text, '')), "+
			"websearch_to_tsquery('simple', $1)) AS _text_score "+
			"FROM %s "+
			"WHERE to_tsvector('simple', coalesce(text, '')) @@ "+
			"websearch_to_tsquery('simple', $2) "+
			"ORDER BY _text_score DESC LIMIT $3",
		cols, s.table)
	raw, err := s.selectRows(ctx, sql, query, query, limit)
	if err != nil {
		return nil, err
	}
	return zipRows(raw, append(append([]string{}, euColumns...), "_text_score")), nil
}

// Scan returns all rows in this leaf — the corpus for lexical/structure signals.
// A nil limit means no limit. Mirrors PostgresVectorStore.scan.
func (s *PostgresVectorStore) Scan(limit *int) ([]Row, error) {
	ctx := context.Background()
	cols := strings.Join(euColumns, ", ")
	sql := fmt.Sprintf("SELECT %s FROM %s", cols, s.table)
	var args []any
	if limit != nil {
		sql += " LIMIT $1"
		args = append(args, *limit)
	}
	raw, err := s.selectRows(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return zipRows(raw, euColumns), nil
}

// zipRows pairs each result tuple with the column names into a Row map.
func zipRows(raw [][]any, cols []string) []Row {
	out := make([]Row, 0, len(raw))
	for _, vals := range raw {
		row := make(Row, len(cols))
		for i, c := range cols {
			if i < len(vals) {
				row[c] = vals[i]
			}
		}
		out = append(out, row)
	}
	return out
}

// rowVector extracts the "vector" field as []float64, tolerating []float64,
// []float32, and []any (the JSON-decoded shape).
func rowVector(row Row) ([]float64, error) {
	switch v := row["vector"].(type) {
	case []float64:
		return v, nil
	case []float32:
		out := make([]float64, len(v))
		for i, x := range v {
			out[i] = float64(x)
		}
		return out, nil
	case []any:
		out := make([]float64, len(v))
		for i, x := range v {
			f, ok := toFloat(x)
			if !ok {
				return nil, fmt.Errorf("storage: vector element %d is %T, not numeric", i, x)
			}
			out[i] = f
		}
		return out, nil
	default:
		return nil, fmt.Errorf("storage: row %q has no numeric vector (got %T)", row["eu_id"], row["vector"])
	}
}

func toFloat(x any) (float64, bool) {
	switch n := x.(type) {
	case float64:
		return n, true
	case float32:
		return float64(n), true
	case int:
		return float64(n), true
	case int64:
		return float64(n), true
	default:
		return 0, false
	}
}

// PostgresTextSearch is the text-search half of the Postgres backend pairing.
// Postgres ranks text natively (tsvector), so this delegates to the store's
// SearchText — sharing its connection and leaf table. Mirrors the Python
// PostgresTextSearch. (The store itself already satisfies TextSearch; use this
// name when wiring the text seam explicitly.)
type PostgresTextSearch struct {
	store *PostgresVectorStore
}

// TextPluginVersion mirrors PostgresTextSearch.plugin_version in Python.
const TextPluginVersion = "postgres-text-search-v1"

// NewPostgresTextSearch pairs a text seam onto an existing store.
func NewPostgresTextSearch(store *PostgresVectorStore) *PostgresTextSearch {
	return &PostgresTextSearch{store: store}
}

// SearchText delegates to the store's native tsvector ranking.
func (t *PostgresTextSearch) SearchText(query string, limit int) ([]Row, error) {
	return t.store.SearchText(query, limit)
}

// Compile-time proof the store satisfies both seams.
var (
	_ VectorStore = (*PostgresVectorStore)(nil)
	_ TextSearch  = (*PostgresVectorStore)(nil)
	_ TextSearch  = (*PostgresTextSearch)(nil)
)
