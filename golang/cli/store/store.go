// Package store is the CLI's local evidence backend: a directory of JSONL
// Evidence-Unit rows, one file per partition. It keeps ingest→retrieve→ask fully
// offline and deterministic (no Lance/cgo, no network) — the "backend: local"
// path a fresh project gets by default. The Rust Lance store remains the S3-native
// backend for larger corpora; this is the zero-setup local mirror.
package store

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
)

// Unit is one stored Evidence Unit: a stable id, its source document, the chunk
// text, and (optionally) its dense embedding for vector retrieval.
type Unit struct {
	EuID       string    `json:"eu_id"`
	DocumentID string    `json:"document_id"`
	BlockOrder int       `json:"block_order"`
	ChunkIndex int       `json:"chunk_index"`
	Text       string    `json:"text"`
	Vector     []float64 `json:"vector,omitempty"`
}

// Store is a partitioned, file-backed EU store rooted at a base directory.
type Store struct {
	root string
}

// Open roots a store at baseDir, creating it if absent.
func Open(baseDir string) (*Store, error) {
	if err := os.MkdirAll(baseDir, 0o755); err != nil {
		return nil, err
	}
	return &Store{root: baseDir}, nil
}

// partitionFile is <root>/<partition>/units.jsonl.
func (s *Store) partitionFile(partition string) string {
	if partition == "" {
		partition = "default"
	}
	return filepath.Join(s.root, partition, "units.jsonl")
}

// Upsert appends rows for one document, first removing any prior rows for the
// same document_id (idempotent re-ingest). Rows keep insertion order otherwise.
func (s *Store) Upsert(partition string, rows []Unit) error {
	existing, err := s.Scan(partition)
	if err != nil {
		return err
	}
	incoming := make(map[string]struct{})
	for _, r := range rows {
		incoming[r.DocumentID] = struct{}{}
	}
	kept := existing[:0]
	for _, u := range existing {
		if _, replaced := incoming[u.DocumentID]; !replaced {
			kept = append(kept, u)
		}
	}
	kept = append(kept, rows...)
	return s.writeAll(partition, kept)
}

// Scan returns all units in a partition (empty when the partition is absent).
func (s *Store) Scan(partition string) ([]Unit, error) {
	f, err := os.Open(s.partitionFile(partition))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	defer func() { _ = f.Close() }()

	var out []Unit
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 64*1024), 8*1024*1024)
	for sc.Scan() {
		line := sc.Bytes()
		if len(line) == 0 {
			continue
		}
		var u Unit
		if err := json.Unmarshal(line, &u); err != nil {
			return nil, err
		}
		out = append(out, u)
	}
	return out, sc.Err()
}

// DeleteDocument removes every unit of a document from a partition. Returns the
// number of units removed.
func (s *Store) DeleteDocument(partition, documentID string) (int, error) {
	existing, err := s.Scan(partition)
	if err != nil {
		return 0, err
	}
	kept := existing[:0]
	removed := 0
	for _, u := range existing {
		if u.DocumentID == documentID {
			removed++
			continue
		}
		kept = append(kept, u)
	}
	if removed == 0 {
		return 0, nil
	}
	return removed, s.writeAll(partition, kept)
}

// Documents lists the distinct document ids present in a partition, sorted.
func (s *Store) Documents(partition string) ([]string, error) {
	units, err := s.Scan(partition)
	if err != nil {
		return nil, err
	}
	seen := map[string]struct{}{}
	var out []string
	for _, u := range units {
		if _, ok := seen[u.DocumentID]; !ok {
			seen[u.DocumentID] = struct{}{}
			out = append(out, u.DocumentID)
		}
	}
	sort.Strings(out)
	return out, nil
}

// writeAll atomically replaces a partition's JSONL with rows.
func (s *Store) writeAll(partition string, rows []Unit) error {
	path := s.partitionFile(partition)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), "units-*.tmp")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	w := bufio.NewWriter(tmp)
	enc := json.NewEncoder(w)
	for _, r := range rows {
		if err := enc.Encode(r); err != nil {
			_ = tmp.Close()
			_ = os.Remove(tmpName)
			return err
		}
	}
	if err := w.Flush(); err != nil {
		_ = tmp.Close()
		_ = os.Remove(tmpName)
		return err
	}
	if err := tmp.Close(); err != nil {
		_ = os.Remove(tmpName)
		return err
	}
	return os.Rename(tmpName, path)
}
