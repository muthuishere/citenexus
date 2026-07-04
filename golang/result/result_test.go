package result

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus-go/internal/conform"
)

func strPtr(s string) *string { return &s }

// roundtrip marshals v, parses the JSON back into a generic value, and returns it
// for structural comparison — so numeric 0 vs 0.0 and key order never matter.
func roundtrip(t *testing.T, v any) any {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var parsed any
	if err := json.Unmarshal(raw, &parsed); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	return parsed
}

// TestResultRoundtripConformance proves the Go Result serializes byte-compatibly
// with the pinned §7 fixture. For each case the equivalent Result is constructed
// in Go, serialized, re-parsed, and deep-compared against the fixture's parsed
// "result". Follows the tokenize exemplar: assert over ALL cases, no leniency.
func TestResultRoundtripConformance(t *testing.T) {
	var cases []struct {
		Name   string `json:"name"`
		Result any    `json:"result"`
	}
	conform.Case(t, "result_roundtrip.json", &cases)

	if len(cases) != 2 {
		t.Fatalf("expected 2 result_roundtrip cases, got %d", len(cases))
	}

	answered := Result{
		Answer:         "The employee shall not disclose confidential information.",
		AnswerLanguage: "en",
		Mode:           TrustModeStrict,
		Evidence: EvidenceSignals{
			Decision:            DecisionAnswered,
			SupportingSources:   1,
			DistinctDocuments:   1,
			AllClaimsVerified:   true,
			LanguagesInEvidence: []string{"en"},
		},
		Claims: []Claim{
			{
				Claim:     "The employee shall not disclose confidential information.",
				Supported: true,
				Sources:   []string{"nda::0"},
			},
		},
		Sources: []SourceRef{
			{
				Document:        "nda",
				Passage:         "The employee shall not disclose confidential information.",
				PassageLanguage: "en",
				SourceURI:       strPtr("raw/workspace=default/nda-sha"),
			},
		},
		MissingEvidence: []string{},
		Conflicts:       []string{},
		Provenance: []ProvenanceEntry{
			{
				Claim:        "The employee shall not disclose confidential information.",
				EvidenceUnit: "nda::0",
				DocumentID:   "nda",
				S3Object:     "raw/workspace=default/nda-sha",
				Checksum:     "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				ProducedBy:   map[string]any{"embedding": "fake-hashing"},
			},
		},
	}

	refused := Refused(TrustModeStrict)

	built := []Result{answered, refused}
	for i, c := range cases {
		got := roundtrip(t, built[i])
		if !reflect.DeepEqual(got, c.Result) {
			t.Errorf("case %q: Result JSON mismatch\n got: %#v\nwant: %#v", c.Name, got, c.Result)
		}
	}
}
