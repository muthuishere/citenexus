package gate

import (
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// expectedFaithfulCounts pins the bucket sizes of conformance/cases/faithful.json.
// Iterating every case is only a contract while the case list cannot silently
// shrink underneath it.
var expectedFaithfulCounts = map[string]int{
	"supported": 7,
	"relevance": 5,
}

type faithfulFixture struct {
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

func loadFaithful(t *testing.T) faithfulFixture {
	t.Helper()
	var fixture faithfulFixture
	conform.Case(t, "faithful.json", &fixture)
	return fixture
}

func assertFaithfulCounts(t *testing.T, fixture faithfulFixture) {
	t.Helper()
	for name, got := range map[string]int{
		"supported": len(fixture.Supported),
		"relevance": len(fixture.Relevance),
	} {
		if want := expectedFaithfulCounts[name]; got != want {
			t.Fatalf("faithful.json bucket %q: got %d vectors, want %d", name, got, want)
		}
	}
}

func TestFaithfulVectorBucketSizes(t *testing.T) {
	assertFaithfulCounts(t, loadFaithful(t))
}

// The gates are proven against the shared fixture — every "supported" and
// "relevance" case must match the Python reference (citenexus.answer.verify)
// exactly. Follows the tokenize exemplar: load the fixture, assert over ALL
// cases, no leniency.
func TestGateConformance(t *testing.T) {
	fixture := loadFaithful(t)
	assertFaithfulCounts(t, fixture)

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
