package tokenize

import (
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// The ADR-0011 per-script golden fixture. The CLAIM (SupportedScripts) and the
// EVIDENCE for it (conformance/cases/tokenize_v2.json) are checked against each
// other here: no script may be claimed as supported without a golden fixture.
type tokenizeV2Fixture struct {
	TokenizerVersion  int      `json:"tokenizer_version"`
	SupportedScripts  []string `json:"supported_scripts"`
	ContinuousScripts []string `json:"continuous_scripts"`
	UnrelatedPassage  string   `json:"unrelated_passage"`
	Supported         []struct {
		Script             string   `json:"script"`
		Text               string   `json:"text"`
		Tokens             []string `json:"tokens"`
		V1Tokens           []string `json:"v1_tokens"`
		SelfSupported      bool     `json:"self_supported"`
		UnrelatedSupported bool     `json:"unrelated_supported"`
		UnsupportedScripts []string `json:"unsupported_scripts"`
	} `json:"supported"`
	Unclaimed []struct {
		Script             string   `json:"script"`
		Text               string   `json:"text"`
		UnsupportedScripts []string `json:"unsupported_scripts"`
	} `json:"unclaimed"`
	Unicode []struct {
		Input  string   `json:"input"`
		Tokens []string `json:"tokens"`
	} `json:"unicode"`
}

func loadTokenizeV2(t *testing.T) tokenizeV2Fixture {
	t.Helper()
	var f tokenizeV2Fixture
	conform.Case(t, "tokenize_v2.json", &f)
	return f
}

func TestTokenizeV2FixturePinsTheVersion(t *testing.T) {
	if got := loadTokenizeV2(t).TokenizerVersion; got != TokenizerVersion {
		t.Fatalf("tokenizer_version = %d, want %d", got, TokenizerVersion)
	}
}

// The embedded scripts.json is a COPY of the canonical claim in
// conformance/cases/tokenize_v2.json (ADR-0010 tier 2: one definition, generated
// copies, a test that pins them together). This is the Go mirror of
// TestPolarityTableMatchesConformance in golang/gate.
func TestScriptTableMatchesConformance(t *testing.T) {
	f := loadTokenizeV2(t)
	if got := SupportedScripts(); !reflect.DeepEqual(got, f.SupportedScripts) {
		t.Fatalf("embedded scripts.json diverged from conformance:\n got  %v\n want %v", got, f.SupportedScripts)
	}
	if got := ContinuousScripts(); !reflect.DeepEqual(got, f.ContinuousScripts) {
		t.Fatalf("embedded scripts.json diverged from conformance:\n got  %v\n want %v", got, f.ContinuousScripts)
	}
	claimed := map[string]bool{}
	for _, s := range f.SupportedScripts {
		claimed[s] = true
	}
	for _, c := range f.Supported {
		if !claimed[c.Script] {
			t.Fatalf("fixture carries a case for unclaimed script %q", c.Script)
		}
		delete(claimed, c.Script)
	}
	if len(claimed) != 0 {
		t.Fatalf("claimed scripts with no golden fixture: %v", claimed)
	}
}

// A mis-sorted table would silently mis-classify via the binary search.
func TestScriptRangesAreSorted(t *testing.T) {
	for i := 1; i < len(scriptRanges); i++ {
		if scriptRanges[i-1].last >= scriptRanges[i].first {
			t.Fatalf("script ranges must be sorted and disjoint: %v then %v", scriptRanges[i-1], scriptRanges[i])
		}
	}
}

func TestEveryClaimedScriptTokenizes(t *testing.T) {
	for _, c := range loadTokenizeV2(t).Supported {
		got := TokenizeV2(c.Text)
		if !reflect.DeepEqual(got, c.Tokens) {
			t.Fatalf("%s: TokenizeV2 = %q, want %q", c.Script, got, c.Tokens)
		}
		if len(c.Tokens) == 0 {
			t.Fatalf("%s: fixture claims support but expects zero tokens", c.Script)
		}
	}
}

// v1 must NOT be "fixed" — the shipped vectors and every index already built
// under it depend on the ASCII behavior.
func TestV1DefectStaysPinned(t *testing.T) {
	for _, c := range loadTokenizeV2(t).Supported {
		got := Tokenize(c.Text)
		want := c.V1Tokens
		if want == nil {
			want = []string{}
		}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("%s: v1 Tokenize = %q, want %q", c.Script, got, want)
		}
	}
}

func TestClaimedScriptsReportNoCapabilityGap(t *testing.T) {
	for _, c := range loadTokenizeV2(t).Supported {
		if got := UnsupportedScripts(c.Text); len(got) != 0 {
			t.Fatalf("%s: UnsupportedScripts = %v, want []", c.Script, got)
		}
		if len(c.UnsupportedScripts) != 0 {
			t.Fatalf("%s: fixture disagrees with itself", c.Script)
		}
	}
}

func TestUnclaimedScriptsAreReportedAsACapabilityGap(t *testing.T) {
	f := loadTokenizeV2(t)
	if len(f.Unclaimed) == 0 {
		t.Fatal("the unclaimed half of the matrix must not be empty")
	}
	for _, c := range f.Unclaimed {
		got := UnsupportedScripts(c.Text)
		if !reflect.DeepEqual(got, c.UnsupportedScripts) {
			t.Fatalf("%s: UnsupportedScripts = %v, want %v", c.Script, got, c.UnsupportedScripts)
		}
		if !reflect.DeepEqual(c.UnsupportedScripts, []string{c.Script}) {
			t.Fatalf("%s: fixture disagrees with itself: %v", c.Script, c.UnsupportedScripts)
		}
	}
}

func TestUnicodeMechanicsVectors(t *testing.T) {
	for _, c := range loadTokenizeV2(t).Unicode {
		got := TokenizeV2(c.Input)
		if !reflect.DeepEqual(got, c.Tokens) {
			t.Fatalf("input %q: TokenizeV2 = %q, want %q", c.Input, got, c.Tokens)
		}
	}
}

// v2 is a strict superset of v1 on pure-ASCII input — that equivalence is why
// moving BM25 and the gate onto v2 left every shipped vector unchanged.
func TestV2AgreesWithV1OnAsciiVectors(t *testing.T) {
	var cases []struct {
		Input  string   `json:"input"`
		Tokens []string `json:"tokens"`
	}
	conform.Case(t, "tokenize.json", &cases)
	if len(cases) == 0 {
		t.Fatal("no v1 tokenize cases loaded")
	}
	for _, c := range cases {
		if !isASCIIWords(c.Input) {
			continue
		}
		if got := TokenizeV2(c.Input); !reflect.DeepEqual(got, Tokenize(c.Input)) {
			t.Fatalf("input %q: v2 = %q diverges from v1 = %q on ASCII input", c.Input, got, Tokenize(c.Input))
		}
	}
}

func isASCIIWords(s string) bool {
	for _, r := range s {
		if r > 127 {
			return false
		}
	}
	return true
}
