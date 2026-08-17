package gate

import (
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// expectedMultilingualGateCounts pins the "gate" buckets of
// conformance/cases/multilingual.json as this package consumes them. Four
// packages read that file; each pins its own buckets so none can pass a
// shrunken fixture.
var expectedMultilingualGateCounts = map[string]int{
	"gate.supported": 3,
	"gate.relevance": 3,
}

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

	for name, got := range map[string]int{
		"gate.supported": len(fixture.Gate.Supported),
		"gate.relevance": len(fixture.Gate.Relevance),
	} {
		if want := expectedMultilingualGateCounts[name]; got != want {
			t.Fatalf("multilingual.json bucket %q: got %d vectors, want %d", name, got, want)
		}
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
