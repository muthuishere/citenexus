package gate

import (
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// The gates are proven against the shared fixture — every "supported" and
// "relevance" case must match the Python reference (citenexus.answer.verify)
// exactly. Follows the tokenize exemplar: load the fixture, assert over ALL
// cases, no leniency.
func TestGateConformance(t *testing.T) {
	var fixture struct {
		Supported []struct {
			Answer    string `json:"answer"`
			Passage   string `json:"passage"`
			Supported bool   `json:"supported"`
		} `json:"supported"`
		Relevance []struct {
			Query    string `json:"query"`
			Passage  string `json:"passage"`
			Relevant bool   `json:"relevant"`
		} `json:"relevance"`
	}
	conform.Case(t, "faithful.json", &fixture)

	total := len(fixture.Supported) + len(fixture.Relevance)
	if total == 0 {
		t.Fatal("no faithful cases loaded")
	}

	for _, c := range fixture.Supported {
		if got := IsSupported(c.Answer, c.Passage); got != c.Supported {
			t.Errorf("IsSupported(%q, %q) = %v, want %v", c.Answer, c.Passage, got, c.Supported)
		}
	}

	for _, c := range fixture.Relevance {
		if got := HasRelevanceOverlap(c.Query, c.Passage); got != c.Relevant {
			t.Errorf("HasRelevanceOverlap(%q, %q) = %v, want %v", c.Query, c.Passage, got, c.Relevant)
		}
	}
}
