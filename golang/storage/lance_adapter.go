//go:build citenexus_ffi

// LanceVectorStore adapts the CGo `core` package (the Rust LanceDB store) to the
// storage.VectorStore seam, so pgvector and LanceDB are interchangeable peers —
// the same arrangement Python has with lance_store.LanceVectorStore alongside
// postgres_store.PostgresVectorStore, both behind the VectorStore Protocol.
//
// Behind the `citenexus_ffi` build tag because it depends on the CGo core; the
// pure-Go PostgresVectorStore has no such requirement and always compiles.
package storage

import (
	"encoding/json"
	"errors"
	"fmt"

	"github.com/muthuishere/citenexus/golang/core"
)

// LanceVectorStore wraps a *core.Store (one leaf Lance database) as a
// storage.VectorStore. LanceDB does NOT rank text natively, so it deliberately
// does not implement TextSearch — the in-core BM25-lite over Scan() is used.
type LanceVectorStore struct {
	store *core.Store
}

// LancePluginVersion mirrors the reference LanceVectorStore tag.
const LancePluginVersion = "lance-vector-v1"

// NewLanceVectorStore adapts an already-opened core.Store to the seam.
func NewLanceVectorStore(store *core.Store) *LanceVectorStore {
	return &LanceVectorStore{store: store}
}

// OpenLanceVectorStore opens (or creates) the leaf Lance database at uri and
// wraps it. optsJSON is a JSON object of storage options or "".
func OpenLanceVectorStore(uri, optsJSON string) (*LanceVectorStore, error) {
	s, err := core.Open(uri, optsJSON)
	if err != nil {
		return nil, err
	}
	return &LanceVectorStore{store: s}, nil
}

// checkErr inspects the C ABI JSON for an {"error":...} envelope.
func checkErr(raw string) error {
	var env struct {
		Error string `json:"error"`
	}
	if json.Unmarshal([]byte(raw), &env) == nil && env.Error != "" {
		return errors.New("citenexus core: " + env.Error)
	}
	return nil
}

func (l *LanceVectorStore) Upsert(rows []Row) error {
	if len(rows) == 0 {
		return nil
	}
	buf, err := json.Marshal(rows)
	if err != nil {
		return err
	}
	return checkErr(l.store.Upsert(string(buf)))
}

func (l *LanceVectorStore) Search(vector []float64, limit int) ([]Row, error) {
	buf, err := json.Marshal(vector)
	if err != nil {
		return nil, err
	}
	return decodeRows(l.store.Search(string(buf), limit))
}

func (l *LanceVectorStore) Scan(limit *int) ([]Row, error) {
	n := -1 // core convention: <0 means no limit
	if limit != nil {
		n = *limit
	}
	return decodeRows(l.store.Scan(n))
}

// decodeRows parses the core's JSON array result into []Row (or surfaces the
// {"error":...} envelope).
func decodeRows(raw string) ([]Row, error) {
	if err := checkErr(raw); err != nil {
		return nil, err
	}
	var rows []Row
	if err := json.Unmarshal([]byte(raw), &rows); err != nil {
		return nil, fmt.Errorf("citenexus core: decode rows: %w", err)
	}
	return rows, nil
}

// Drop drops the leaf (isolation = drop a table, mirroring the pg peer).
func (l *LanceVectorStore) Drop() error { return checkErr(l.store.Drop()) }

// Close releases the underlying core store handle.
func (l *LanceVectorStore) Close() { l.store.Close() }

var _ VectorStore = (*LanceVectorStore)(nil)
