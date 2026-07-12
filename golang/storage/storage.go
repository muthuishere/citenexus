// Package storage is the Go port of citenexus.storage — the vector-store and
// text-search seams (spec storage-partition-seam, §6b/§10).
//
// Storage is layered: raw blobs / manifests / graph / wiki artifacts live behind
// a StorageBackend (not modelled here yet), while the retrievable per-leaf index
// lives behind two seams that mirror the Python Protocols in
// python/src/citenexus/storage/protocols.py exactly:
//
//   - VectorStore — the per-leaf index every consumer uses through exactly three
//     methods (Upsert / Search / Scan). The CGo `core` package (LanceDB, behind
//     the `citenexus_ffi` build tag) is the zero-infra REFERENCE implementation
//     and stays the default; PostgresVectorStore (pgvector) lets a team bring
//     their existing Postgres instead. See lance_adapter.go for the core bridge.
//   - TextSearch — OPTIONAL native lexical search. A backend that can rank text
//     itself (Postgres tsvector) implements it; a backend that can't (LanceDB)
//     simply doesn't, and the in-core BM25-lite over Scan() is used.
//
// Rows are plain maps with the EU keys the ingest pipeline writes: eu_id,
// vector, text, document_id, language, page, checksum, raw_uri. Search results
// additionally carry "_distance"; SearchText results carry "_text_score". This
// map shape mirrors the Python dict rows byte-for-byte over the JSON wire.
package storage

import (
	"regexp"
	"strconv"
	"strings"
)

// Row is one Evidence-Unit record — the Go analogue of the Python dict row. Keys
// are the EU column names; Search adds "_distance", SearchText adds "_text_score".
type Row = map[string]any

// VectorStore is the per-leaf retrievable index — the seam all consumers go
// through. Mirrors python storage.protocols.VectorStore (upsert/search/scan).
type VectorStore interface {
	// Upsert inserts or updates EU rows keyed by eu_id (idempotent).
	Upsert(rows []Row) error
	// Search returns the nearest rows to vector (each with "_distance"); empty
	// slice when the leaf is empty.
	Search(vector []float64, limit int) ([]Row, error)
	// Scan returns all rows in this leaf — the corpus for lexical/structure
	// signals. A nil limit means no limit.
	Scan(limit *int) ([]Row, error)
	// DeleteDocument removes every row carrying documentID — the row-level
	// inverse of an ingest (document-revoke). A no-op (nil error) when nothing
	// matches or the leaf has no table yet. Mirrors
	// python storage.protocols.VectorStore.delete_document.
	DeleteDocument(documentID string) error
}

// TextSearch is native lexical ranking, when the backend can do it itself.
// Mirrors python storage.protocols.TextSearch (search_text).
type TextSearch interface {
	// SearchText returns rows ranked by the backend's own text relevance (each
	// with "_text_score"); empty slice when nothing matches.
	SearchText(query string, limit int) ([]Row, error)
}

// euColumns is the payload column order shared by every SELECT/INSERT — mirrors
// _COLUMNS in postgres_store.py (vector is handled out-of-band).
var euColumns = []string{"eu_id", "text", "document_id", "language", "page", "checksum", "raw_uri"}

var identRe = regexp.MustCompile(`[^a-z0-9_]+`)

// TableNameFor builds a safe per-leaf table name from the configured prefix +
// partition segment. Mirrors table_name_for() in postgres_store.py.
func TableNameFor(prefix, partitionSegment string) string {
	leaf := strings.Trim(identRe.ReplaceAllString(strings.ToLower(partitionSegment), "_"), "_")
	pfx := strings.Trim(identRe.ReplaceAllString(strings.ToLower(prefix), "_"), "_")
	return pfx + "_" + leaf
}

// vectorLiteral renders a float slice as a pgvector text literal "[a,b,c]".
// Mirrors _vector_literal() in postgres_store.py (Python str(float(x))).
func vectorLiteral(vector []float64) string {
	parts := make([]string, len(vector))
	for i, x := range vector {
		parts[i] = strconv.FormatFloat(x, 'g', -1, 64)
	}
	return "[" + strings.Join(parts, ",") + "]"
}
