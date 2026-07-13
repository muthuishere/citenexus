package store

import (
	"path/filepath"
	"testing"
)

func TestUpsertScanRoundTrip(t *testing.T) {
	s, err := Open(filepath.Join(t.TempDir(), "data"))
	if err != nil {
		t.Fatal(err)
	}
	rows := []Unit{
		{EuID: "doc1:b0:c0", DocumentID: "doc1", Text: "the cat sat", Vector: []float64{0.1, 0.2}},
		{EuID: "doc1:b0:c1", DocumentID: "doc1", Text: "on the mat"},
	}
	if err := s.Upsert("default", rows); err != nil {
		t.Fatal(err)
	}
	got, err := s.Scan("default")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0].EuID != "doc1:b0:c0" || got[1].Text != "on the mat" {
		t.Fatalf("round-trip mismatch: %+v", got)
	}
}

func TestUpsertIsIdempotentPerDocument(t *testing.T) {
	s, _ := Open(filepath.Join(t.TempDir(), "data"))
	_ = s.Upsert("default", []Unit{{EuID: "d1:0", DocumentID: "d1", Text: "v1"}})
	_ = s.Upsert("default", []Unit{{EuID: "d2:0", DocumentID: "d2", Text: "other"}})
	// Re-ingest d1 with new content — must replace, not duplicate.
	_ = s.Upsert("default", []Unit{{EuID: "d1:0", DocumentID: "d1", Text: "v2"}})

	got, _ := s.Scan("default")
	if len(got) != 2 {
		t.Fatalf("want 2 units after re-ingest, got %d: %+v", len(got), got)
	}
	byDoc := map[string]string{}
	for _, u := range got {
		byDoc[u.DocumentID] = u.Text
	}
	if byDoc["d1"] != "v2" {
		t.Errorf("d1 not replaced: %q", byDoc["d1"])
	}
	if byDoc["d2"] != "other" {
		t.Errorf("d2 disturbed: %q", byDoc["d2"])
	}
}

func TestDeleteDocument(t *testing.T) {
	s, _ := Open(filepath.Join(t.TempDir(), "data"))
	_ = s.Upsert("default", []Unit{
		{EuID: "d1:0", DocumentID: "d1", Text: "a"},
		{EuID: "d2:0", DocumentID: "d2", Text: "b"},
	})
	n, err := s.DeleteDocument("default", "d1")
	if err != nil || n != 1 {
		t.Fatalf("delete: n=%d err=%v", n, err)
	}
	docs, _ := s.Documents("default")
	if len(docs) != 1 || docs[0] != "d2" {
		t.Errorf("after delete want [d2], got %v", docs)
	}
}

func TestScanAbsentPartitionIsEmpty(t *testing.T) {
	s, _ := Open(filepath.Join(t.TempDir(), "data"))
	got, err := s.Scan("nope")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 0 {
		t.Errorf("want empty, got %+v", got)
	}
}
