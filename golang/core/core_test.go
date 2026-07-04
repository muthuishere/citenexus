//go:build citenexus_ffi

package core

import (
	"encoding/json"
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
