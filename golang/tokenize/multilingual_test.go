package tokenize

import (
	"reflect"
	"regexp"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// naiveTokenize is a DELIBERATELY-divergent tokenizer: a bare simple-case
// lowercase with no İ expansion — exactly the trap ADR-0006 warns about. It is
// here to prove the multilingual corpus BITES: at least one committed vector
// must reject it, so the suite could never pass a dot-dropping port silently.
func naiveTokenize(text string) []string {
	toks := regexp.MustCompile(`[a-z0-9]+`).FindAllString(strings.ToLower(text), -1)
	if toks == nil {
		return []string{}
	}
	return toks
}

// TestMultilingualCorpusBites is the red→green guarantee (task 2.4): the real
// tokenizer passes every vector, and the divergent one is caught by at least one.
func TestMultilingualCorpusBites(t *testing.T) {
	var fixture struct {
		Tokenize []struct {
			Input  string   `json:"input"`
			Tokens []string `json:"tokens"`
		} `json:"tokenize"`
	}
	conform.Case(t, "multilingual.json", &fixture)

	bites := false
	for _, c := range fixture.Tokenize {
		if !reflect.DeepEqual(naiveTokenize(c.Input), c.Tokens) {
			bites = true // a naive simple-lowercase tokenizer diverges on this vector
		}
	}
	if !bites {
		t.Fatal("the multilingual corpus did not catch a naive simple-lowercase tokenizer — it has no teeth")
	}
}

// The ADR-0006 anti-drift corpus: the tokenizer STAYS per host language, so this
// multilingual/Unicode-edge suite is what pins it against drift. Turkish dotted
// İ, German ß, NFC vs NFD, CJK, and combining marks must tokenize byte-identical
// to the Python reference — a simple 1:1 lowercase that drops İ's dot fails here.
func TestTokenizeMultilingualConformance(t *testing.T) {
	var fixture struct {
		Tokenize []struct {
			Input  string   `json:"input"`
			Tokens []string `json:"tokens"`
		} `json:"tokenize"`
	}
	conform.Case(t, "multilingual.json", &fixture)

	if len(fixture.Tokenize) == 0 {
		t.Fatal("no multilingual tokenize cases loaded")
	}
	for _, c := range fixture.Tokenize {
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
