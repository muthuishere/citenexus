//go:build citenexus_ffi

package core

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestVersion(t *testing.T) {
	v := Version()
	if v == "" {
		t.Fatal("empty core version")
	}
	t.Logf("citenexus-core version: %s", v)
}

func TestExtractPlain(t *testing.T) {
	out := Extract([]byte("Hello CiteNexus.\n\nSecond paragraph here."), "plain", "doc1")
	if strings.Contains(out, `"error"`) {
		t.Fatalf("extract returned error: %s", out)
	}
	var doc struct {
		DocumentID string `json:"document_id"`
		Blocks     []struct {
			Text string `json:"text"`
		} `json:"blocks"`
	}
	if err := json.Unmarshal([]byte(out), &doc); err != nil {
		t.Fatalf("extract output not valid JSON: %v\n%s", err, out)
	}
	if doc.DocumentID != "doc1" {
		t.Fatalf("document_id = %q, want doc1", doc.DocumentID)
	}
	if len(doc.Blocks) == 0 {
		t.Fatalf("expected at least one block, got none: %s", out)
	}
}

// TestStoreRoundTrip drives the real Rust Lance store over a temp directory URI:
// open → upsert one row → scan finds it → search finds it.
func TestStoreRoundTrip(t *testing.T) {
	dir := t.TempDir()
	store, err := Open(dir, "")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()

	const euID = "eu-roundtrip-1"
	row := map[string]any{
		"eu_id":  euID,
		"vector": []float64{0.1, 0.2, 0.3, 0.4},
		"text":   "the employee may disclose under NDA carve-outs",
	}
	rowsJSON, err := json.Marshal([]any{row})
	if err != nil {
		t.Fatalf("marshal row: %v", err)
	}
	if out := store.Upsert(string(rowsJSON)); strings.Contains(out, `"error"`) {
		t.Fatalf("upsert error: %s", out)
	}

	// scan returns the row we inserted.
	scanOut := store.Scan(-1)
	if strings.Contains(scanOut, `"error"`) {
		t.Fatalf("scan error: %s", scanOut)
	}
	var scanned []map[string]any
	if err := json.Unmarshal([]byte(scanOut), &scanned); err != nil {
		t.Fatalf("scan output not JSON: %v\n%s", err, scanOut)
	}
	if len(scanned) != 1 || scanned[0]["eu_id"] != euID {
		t.Fatalf("scan did not return the upserted row: %s", scanOut)
	}

	// search returns the row we inserted (nearest to its own vector).
	searchOut := store.Search("[0.1, 0.2, 0.3, 0.4]", 5)
	if strings.Contains(searchOut, `"error"`) {
		t.Fatalf("search error: %s", searchOut)
	}
	var found []map[string]any
	if err := json.Unmarshal([]byte(searchOut), &found); err != nil {
		t.Fatalf("search output not JSON: %v\n%s", err, searchOut)
	}
	if len(found) == 0 || found[0]["eu_id"] != euID {
		t.Fatalf("search did not return the upserted row: %s", searchOut)
	}
}

// TestDetect exercises the real lid.176 detector when the model is present, and
// skips otherwise (the binding still compiled — that's the point). Set
// CITENEXUS_LID176_PATH to the model file to run it.
func TestDetect(t *testing.T) {
	modelPath := os.Getenv("CITENEXUS_LID176_PATH")
	if modelPath == "" {
		modelPath = "../../models/lid.176.bin"
	}
	if _, err := os.Stat(modelPath); err != nil {
		t.Skipf("lid.176 model not present at %q (set CITENEXUS_LID176_PATH); skipping detect test", modelPath)
	}
	out, err := Detect(modelPath, "The quick brown fox jumps over the lazy dog.")
	if err != nil {
		t.Fatalf("detect: %v", err)
	}
	if strings.Contains(out, `"error"`) {
		t.Fatalf("detect returned error: %s", out)
	}
	var det struct {
		Language   string  `json:"language"`
		Confidence float64 `json:"confidence"`
	}
	if err := json.Unmarshal([]byte(out), &det); err != nil {
		t.Fatalf("detect output not JSON: %v\n%s", err, out)
	}
	if det.Language != "en" {
		t.Fatalf("detected language = %q, want en (%s)", det.Language, out)
	}
}
