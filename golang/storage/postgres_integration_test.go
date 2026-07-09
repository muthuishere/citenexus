package storage

import (
	"context"
	"fmt"
	"math/rand"
	"net"
	"os"
	"testing"
	"time"
)

// Opt-in Postgres/pgvector round-trip — the real-server proof for the second
// VectorStore backend: upsert -> dense search (pgvector cosine) -> NATIVE text
// search (tsvector) -> scan -> idempotent re-upsert. Mirrors the Python
// tests/storage/test_integration_postgres.py gating: skips unless Postgres
// answers on the compose port. Bring it up with `task postgres:up` (compose).
//
//   CITENEXUS_PG_DSN  (default postgresql://citenexus:citenexus@localhost:15432/citenexus)
//   CITENEXUS_PG_PORT (default 15432)

func pgDSN() string {
	if v := os.Getenv("CITENEXUS_PG_DSN"); v != "" {
		return v
	}
	return "postgresql://citenexus:citenexus@localhost:15432/citenexus"
}

func pgPort() string {
	if v := os.Getenv("CITENEXUS_PG_PORT"); v != "" {
		return v
	}
	return "15432"
}

func postgresUp() bool {
	conn, err := net.DialTimeout("tcp", net.JoinHostPort("localhost", pgPort()), 2*time.Second)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}

func TestPostgresRoundTrip(t *testing.T) {
	if !postgresUp() {
		t.Skipf("Postgres not reachable on localhost:%s", pgPort())
	}

	table := TableNameFor("citenexus_it", fmt.Sprintf("workspace=%08x", rand.Uint32()))
	store := NewPostgresVectorStore(pgDSN(), table, nil)
	t.Cleanup(func() {
		// Drop the leaf table + close (mirrors the Python finally block).
		if store.conn != nil {
			_, _ = store.conn.Exec(context.Background(), fmt.Sprintf("DROP TABLE IF EXISTS %s", table))
		}
		_ = store.Close(context.Background())
	})

	rows := []Row{
		{
			"eu_id": "nda::0", "vector": []float64{1, 0, 0},
			"text":     "The employee shall not disclose confidential information.",
			"document_id": "nda", "language": "en", "page": 1,
			"checksum": "abc", "raw_uri": "raw/abc",
		},
		{
			"eu_id": "cats::0", "vector": []float64{0, 1, 0},
			"text":     "Cats are small domestic animals.",
			"document_id": "cats", "language": "en", "page": -1,
			"checksum": "def", "raw_uri": "raw/def",
		},
	}

	if err := store.Upsert(rows); err != nil {
		t.Fatalf("upsert: %v", err)
	}

	hits, err := store.Search([]float64{1, 0, 0}, 1)
	if err != nil {
		t.Fatalf("search: %v", err)
	}
	if len(hits) != 1 || hits[0]["eu_id"] != "nda::0" {
		t.Fatalf("search hits = %v", hits)
	}
	if d, ok := hits[0]["_distance"].(float64); !ok || d >= 0.01 {
		t.Fatalf("distance = %v", hits[0]["_distance"])
	}

	textHits, err := store.SearchText("confidential disclose", 2)
	if err != nil {
		t.Fatalf("search_text: %v", err)
	}
	if len(textHits) == 0 || textHits[0]["eu_id"] != "nda::0" {
		t.Fatalf("text hits = %v", textHits)
	}

	all, err := store.Scan(nil)
	if err != nil {
		t.Fatalf("scan: %v", err)
	}
	if len(all) != 2 {
		t.Fatalf("scan len = %d, want 2", len(all))
	}

	// Idempotent re-upsert.
	if err := store.Upsert(rows); err != nil {
		t.Fatalf("re-upsert: %v", err)
	}
	all, _ = store.Scan(nil)
	if len(all) != 2 {
		t.Fatalf("scan after re-upsert = %d, want 2", len(all))
	}
}

// TestSearchMissingTableIsEmpty proves an undefined leaf returns [] not an error
// (parity with LanceDB), against a live server without creating the table.
func TestSearchMissingTableIsEmpty(t *testing.T) {
	if !postgresUp() {
		t.Skipf("Postgres not reachable on localhost:%s", pgPort())
	}
	store := NewPostgresVectorStore(pgDSN(), TableNameFor("citenexus_it", fmt.Sprintf("void=%08x", rand.Uint32())), nil)
	t.Cleanup(func() { _ = store.Close(context.Background()) })
	hits, err := store.Search([]float64{1, 0, 0}, 5)
	if err != nil {
		t.Fatalf("search on missing table erred: %v", err)
	}
	if len(hits) != 0 {
		t.Fatalf("missing-table search = %v, want empty", hits)
	}
}
