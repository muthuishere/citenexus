package gate

import (
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// The multilingual anti-drift corpus (ADR-0006) run through the cite-or-abstain
// gate — the highest-consequence place drift can hide. An ASCII "Istanbul" is
// NOT supported by a passage whose "İstanbul" the reference splits into
// "i"+"stanbul"; a tokenizer that drops the dot would wrongly report support.
func TestGateMultilingualConformance(t *testing.T) {
	var fixture struct {
		Gate struct {
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
		} `json:"gate"`
	}
	conform.Case(t, "multilingual.json", &fixture)

	total := len(fixture.Gate.Supported) + len(fixture.Gate.Relevance)
	if total == 0 {
		t.Fatal("no multilingual gate cases loaded")
	}
	for _, c := range fixture.Gate.Supported {
		if got := IsSupported(c.Answer, c.Passage); got != c.Supported {
			t.Errorf("IsSupported(%q, %q) = %v, want %v", c.Answer, c.Passage, got, c.Supported)
		}
	}
	for _, c := range fixture.Gate.Relevance {
		if got := HasRelevanceOverlap(c.Query, c.Passage); got != c.Relevant {
			t.Errorf("HasRelevanceOverlap(%q, %q) = %v, want %v", c.Query, c.Passage, got, c.Relevant)
		}
	}
}
