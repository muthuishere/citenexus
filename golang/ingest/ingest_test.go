//go:build citenexus_ffi

package ingest

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/core"
)

// fakeEmbedder is a deterministic, hermetic stand-in for a real embedding model
// (CLAUDE.md: unit tests use deterministic fakes). It returns a fixed-dim vector
// whose first element is the chunk's word count, so different chunks differ.
type fakeEmbedder struct{ dim int }

func (f fakeEmbedder) Embed(text string) ([]float64, error) {
	vec := make([]float64, f.dim)
	vec[0] = float64(len(strings.Fields(text)))
	for i := 1; i < f.dim; i++ {
		vec[i] = float64((len(text) + i) % 7)
	}
	return vec, nil
}

// timeoutEmbedder is the real-world failure the seam exists for: the model dies
// on the Nth chunk. Before ADR-0014 R2 it had nowhere to say so and returned
// make([]float64, dim) — the zero vector ingest then indexed.
type timeoutEmbedder struct {
	dim    int
	calls  int
	failOn int
}

var errEmbedTimeout = errors.New("model call timed out after 30s")

func (e *timeoutEmbedder) Embed(text string) ([]float64, error) {
	e.calls++
	if e.calls == e.failOn {
		return nil, errEmbedTimeout
	}
	return fakeEmbedder{dim: e.dim}.Embed(text)
}

// zeroVectorEmbedder is the dishonest provider: it "succeeds" but hands back a
// vector carrying no signal. The write-path guard is the belt to R2's braces.
type zeroVectorEmbedder struct{ dim int }

func (z zeroVectorEmbedder) Embed(string) ([]float64, error) {
	return make([]float64, z.dim), nil
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

// TestIngestRefusesWhenEmbedFails is the regression for ADR-0014 R2. The spike
// (spikes/model-seam-contract/go) proved that with the old no-error seam a model
// timing out on chunk 2 gave `err = <nil>`, the same row count as a healthy run,
// and a poisoned EU scoring cosine 0.0000 with no flag. Now ingest refuses and
// the store stays empty: fail-closed, all-or-nothing.
func TestIngestRefusesWhenEmbedFails(t *testing.T) {
	store, err := core.Open(t.TempDir(), "")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()

	data := []byte("The employee may disclose the defect.\n\nThe employee may NOT disclose the defect.")
	emb := &timeoutEmbedder{dim: 8, failOn: 2}

	rows, err := Ingest(store, data, "plain", "docFAIL", emb)
	if err == nil {
		t.Fatal("ingest returned nil error after the model failed — the corpus is silently wrong")
	}
	if !errors.Is(err, errEmbedTimeout) {
		t.Fatalf("the model's own error must reach the caller; got %v", err)
	}
	if rows != nil {
		t.Fatalf("ingest returned %d rows on failure; it must return none", len(rows))
	}
	assertStoreEmpty(t, store)
}

// TestIngestRefusesTheZeroVector: even an embedder that reports success must not
// be able to write a signal-free vector into the corpus.
func TestIngestRefusesTheZeroVector(t *testing.T) {
	store, err := core.Open(t.TempDir(), "")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()

	rows, err := Ingest(store, []byte("Hello CiteNexus."), "plain", "docZERO", zeroVectorEmbedder{dim: 8})
	if err == nil {
		t.Fatal("the zero vector was indexed")
	}
	if !strings.Contains(err.Error(), "zero vector") {
		t.Fatalf("error should name the zero vector: %v", err)
	}
	if rows != nil {
		t.Fatalf("ingest returned %d rows on failure; it must return none", len(rows))
	}
	assertStoreEmpty(t, store)
}

// assertStoreEmpty fails unless nothing at all landed in the Lance store.
func assertStoreEmpty(t *testing.T, store *core.Store) {
	t.Helper()
	scanOut := store.Scan(-1)
	if strings.Contains(scanOut, `"error"`) {
		// A store that was never written to may not have a table yet; that is
		// also "nothing landed".
		return
	}
	var scanned []map[string]any
	if err := json.Unmarshal([]byte(scanOut), &scanned); err != nil {
		t.Fatalf("scan output not JSON: %v\n%s", err, scanOut)
	}
	if len(scanned) != 0 {
		t.Fatalf("failed ingest wrote %d rows into the store: %s", len(scanned), scanOut)
	}
}
