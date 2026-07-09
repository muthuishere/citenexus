package storage

import "testing"

// Mirrors the deterministic, IO-free parts of the Python storage reference.

func TestTableNameFor(t *testing.T) {
	got := TableNameFor("citenexus_it", "workspace=ab12cd34")
	want := "citenexus_it_workspace_ab12cd34"
	if got != want {
		t.Fatalf("TableNameFor = %q, want %q", got, want)
	}
	// Mixed case + punctuation collapses to single underscores, trimmed.
	if got := TableNameFor("Cite-Nexus", "org=Acme.Corp/x"); got != "cite_nexus_org_acme_corp_x" {
		t.Fatalf("sanitize = %q", got)
	}
}

func TestVectorLiteral(t *testing.T) {
	if got := vectorLiteral([]float64{1, 0, 0.5}); got != "[1,0,0.5]" {
		t.Fatalf("vectorLiteral = %q", got)
	}
}

func TestConstructionDoesNoIO(t *testing.T) {
	// No connect func, unreachable DSN — construction must not dial (parity with
	// the Python lazy __init__).
	s := NewPostgresVectorStore("postgresql://nope:nope@127.0.0.1:1/none", "t", nil)
	if s.conn != nil {
		t.Fatal("construction opened a connection")
	}
	// Upsert of zero rows is a no-op and still must not dial.
	if err := s.Upsert(nil); err != nil {
		t.Fatalf("empty Upsert erred: %v", err)
	}
	if s.conn != nil {
		t.Fatal("empty Upsert opened a connection")
	}
}

func TestRowVectorShapes(t *testing.T) {
	for _, tc := range []Row{
		{"eu_id": "a", "vector": []float64{1, 2}},
		{"eu_id": "a", "vector": []float32{1, 2}},
		{"eu_id": "a", "vector": []any{float64(1), 2}},
	} {
		v, err := rowVector(tc)
		if err != nil {
			t.Fatalf("rowVector %T: %v", tc["vector"], err)
		}
		if len(v) != 2 || v[0] != 1 || v[1] != 2 {
			t.Fatalf("rowVector %T = %v", tc["vector"], v)
		}
	}
	if _, err := rowVector(Row{"eu_id": "a", "vector": "nope"}); err == nil {
		t.Fatal("expected error for non-numeric vector")
	}
}
