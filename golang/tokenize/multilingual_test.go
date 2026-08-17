package tokenize

import (
	"reflect"
	"regexp"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// expectedMultilingualTokenizeCases pins the "tokenize" bucket of
// conformance/cases/multilingual.json. Four packages read this file; each pins
// the bucket it consumes independently, so a shrunken file cannot pass anywhere.
const expectedMultilingualTokenizeCases = 10

type multilingualTokenizeFixture struct {
	Tokenize []struct {
		Input  string   `json:"input"`
		Tokens []string `json:"tokens"`
	} `json:"tokenize"`
}

func loadMultilingualTokenize(t *testing.T) multilingualTokenizeFixture {
	t.Helper()
	var fixture multilingualTokenizeFixture
	conform.Case(t, "multilingual.json", &fixture)
	return fixture
}

func TestMultilingualTokenizeVectorCount(t *testing.T) {
	if got := len(loadMultilingualTokenize(t).Tokenize); got != expectedMultilingualTokenizeCases {
		t.Fatalf("multilingual.json bucket \"tokenize\": got %d vectors, want %d",
			got, expectedMultilingualTokenizeCases)
	}
}

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
	fixture := loadMultilingualTokenize(t)
	if len(fixture.Tokenize) != expectedMultilingualTokenizeCases {
		t.Fatalf("multilingual.json bucket \"tokenize\": got %d vectors, want %d",
			len(fixture.Tokenize), expectedMultilingualTokenizeCases)
	}

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
	fixture := loadMultilingualTokenize(t)
	if len(fixture.Tokenize) != expectedMultilingualTokenizeCases {
		t.Fatalf("multilingual.json bucket \"tokenize\": got %d vectors, want %d",
			len(fixture.Tokenize), expectedMultilingualTokenizeCases)
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
