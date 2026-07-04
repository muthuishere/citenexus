//go:build citenexus_ffi

package ingest

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/core"
)

// fakeEmbedder is a deterministic, hermetic stand-in for a real embedding model
// (CLAUDE.md: unit tests use deterministic fakes). It returns a fixed-dim vector
// whose first element is the chunk's word count, so different chunks differ.
type fakeEmbedder struct{ dim int }

func (f fakeEmbedder) Embed(text string) []float64 {
	vec := make([]float64, f.dim)
	vec[0] = float64(len(strings.Fields(text)))
	for i := 1; i < f.dim; i++ {
		vec[i] = float64((len(text) + i) % 7)
	}
	return vec
}

// TestIngestRoundTrip drives the real Rust extractor + Lance store end to end
// with a fake embedder over a temp-directory store.
func TestIngestRoundTrip(t *testing.T) {
	store, err := core.Open(t.TempDir(), "")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()

	emb := fakeEmbedder{dim: 8}
	data := []byte("Hello CiteNexus.\n\nSecond paragraph carries different words entirely.")

	rows, err := Ingest(store, data, "plain", "docING", emb)
	if err != nil {
		t.Fatalf("ingest: %v", err)
	}
	if len(rows) == 0 {
		t.Fatal("ingest produced no rows")
	}
	for _, r := range rows {
		if r.EuID == "" || len(r.Vector) != emb.dim || r.Text == "" {
			t.Fatalf("malformed row: %+v", r)
		}
	}

	// The rows really landed in the Rust store: scan them back.
	scanOut := store.Scan(-1)
	if strings.Contains(scanOut, `"error"`) {
		t.Fatalf("scan error: %s", scanOut)
	}
	var scanned []map[string]any
	if err := json.Unmarshal([]byte(scanOut), &scanned); err != nil {
		t.Fatalf("scan output not JSON: %v\n%s", err, scanOut)
	}
	if len(scanned) != len(rows) {
		t.Fatalf("scan returned %d rows, ingested %d", len(scanned), len(rows))
	}

	// A search against the first row's vector finds it back through the engine.
	vecJSON, err := json.Marshal(rows[0].Vector)
	if err != nil {
		t.Fatalf("marshal vector: %v", err)
	}
	searchOut := store.Search(string(vecJSON), 5)
	if strings.Contains(searchOut, `"error"`) {
		t.Fatalf("search error: %s", searchOut)
	}
	var found []map[string]any
	if err := json.Unmarshal([]byte(searchOut), &found); err != nil {
		t.Fatalf("search output not JSON: %v\n%s", err, searchOut)
	}
	if len(found) == 0 {
		t.Fatalf("search found nothing: %s", searchOut)
	}
}
