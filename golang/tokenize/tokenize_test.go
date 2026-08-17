package tokenize

import (
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// expectedTokenizeCases pins the size of conformance/cases/tokenize.json. A
// per-case loop proves nothing if the file silently shrinks, so the count is a
// binding part of the contract, not a "greater than zero" floor.
const expectedTokenizeCases = 11

// TestTokenizeVectorCount fails loudly if the fixture gains or loses vectors.
func TestTokenizeVectorCount(t *testing.T) {
	var cases []struct {
		Input  string   `json:"input"`
		Tokens []string `json:"tokens"`
	}
	conform.Case(t, "tokenize.json", &cases)
	if len(cases) != expectedTokenizeCases {
		t.Fatalf("tokenize.json: got %d cases, want %d", len(cases), expectedTokenizeCases)
	}
}

// The tokenizer is proven against the shared fixture — every case must match the
// Python reference exactly. This test is the EXEMPLAR every §4 algorithm test in
// this port follows: load conformance/cases/<algo>.json, assert byte-identical
// output over ALL cases, no leniency.
func TestTokenizeConformance(t *testing.T) {
	var cases []struct {
		Input  string   `json:"input"`
		Tokens []string `json:"tokens"`
	}
	conform.Case(t, "tokenize.json", &cases)

	if len(cases) != expectedTokenizeCases {
		t.Fatalf("tokenize.json: got %d cases, want %d", len(cases), expectedTokenizeCases)
	}
	for _, c := range cases {
		got := Tokenize(c.Input)
		want := c.Tokens
		if want == nil {
			want = []string{}
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("Tokenize(%q) = %v, want %v", c.Input, got, want)
		}
	}
}
