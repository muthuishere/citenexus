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

// expectedTokenizeV2Counts pins every bucket in
// conformance/cases/tokenize_v2.json. Iterating a bucket asserts nothing about a
// vector that was silently dropped from it.
var expectedTokenizeV2Counts = map[string]int{
	"supported":          14,
	"unclaimed":          11,
	"unicode":            27,
	"supported_scripts":  14,
	"continuous_scripts": 7,
}

func TestTokenizeV2VectorBucketSizes(t *testing.T) {
	f := loadTokenizeV2(t)
	for name, got := range map[string]int{
		"supported":          len(f.Supported),
		"unclaimed":          len(f.Unclaimed),
		"unicode":            len(f.Unicode),
		"supported_scripts":  len(f.SupportedScripts),
		"continuous_scripts": len(f.ContinuousScripts),
	} {
		if want := expectedTokenizeV2Counts[name]; got != want {
			t.Errorf("tokenize_v2.json bucket %q: got %d vectors, want %d", name, got, want)
		}
	}
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
	if len(cases) != expectedTokenizeCases {
		t.Fatalf("tokenize.json: got %d cases, want %d", len(cases), expectedTokenizeCases)
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

// Telugu (U+0C00-U+0C7F) was absent from the range table entirely: it read as a
// NEIGHBOUR plus "unknown" and still emitted six delimited tokens, so BM25
// ranked a script no fixture had ever validated while the answer flow filtered
// every Telugu passage out of the grounding set.
func TestTeluguClassifiesAsItselfAndIsDelimited(t *testing.T) {
	const text = "ఉద్యోగి రహస్య సమాచారాన్ని"
	if got := ScriptsIn(text); !reflect.DeepEqual(got, []string{"telugu"}) {
		t.Fatalf("ScriptsIn = %q, want [telugu]", got)
	}
	if got := UnsupportedScripts(text); len(got) != 0 {
		t.Fatalf("UnsupportedScripts = %q, want none", got)
	}
	want := []string{"ఉద్యోగి", "రహస్య", "సమాచారాన్ని"}
	if got := TokenizeV2(text); !reflect.DeepEqual(got, want) {
		t.Fatalf("TokenizeV2 = %q, want %q (Telugu writes spaces; bigrams would be the mirror defect)", got, want)
	}
}

// Every CLAIMED script must classify to ITSELF — a second script in this list is
// exactly what Telugu's ('devanagari', 'unknown') was.
func TestEveryClaimedScriptSampleClassifiesToItself(t *testing.T) {
	for _, c := range loadTokenizeV2(t).Supported {
		for _, s := range ScriptsIn(c.Text) {
			// Japanese genuinely mixes Han and Hiragana; nothing may be "unknown".
			if s == "unknown" {
				t.Fatalf("%s: sample classifies partly as unknown", c.Script)
			}
			if s != c.Script && !(c.Script == "hiragana" && s == "han") {
				t.Fatalf("%s: sample also classifies as %q", c.Script, s)
			}
		}
	}
}

// The structural half: a script ABSENT from the range table has no validated
// segmentation rule, so it produces NOTHING. BM25 cannot rank it, and the gate
// cannot accept it (an empty claim never aligns).
func TestAScriptAbsentFromTheTableDoesNotTokenize(t *testing.T) {
	for _, text := range []string{"የሰራተኛው ሚስጥራዊ መረጃ", "ᏗᏙᎳᏅᏍᏗ ᎠᏓᏅᏙ", "ཞིབ་འཇུག"} {
		if got := UnsupportedScripts(text); !reflect.DeepEqual(got, []string{"unknown"}) {
			t.Fatalf("%q: UnsupportedScripts = %q, want [unknown]", text, got)
		}
		if got := TokenizeV2(text); len(got) != 0 {
			t.Fatalf("%q: TokenizeV2 = %q, want no tokens", text, got)
		}
	}
	// Only the unknown RUN is dropped — a stray character cannot silence an
	// otherwise-supported passage.
	want := []string{"2026", "policy"}
	if got := TokenizeV2("የሰራተኛው 2026 policy"); !reflect.DeepEqual(got, want) {
		t.Fatalf("TokenizeV2 = %q, want %q", got, want)
	}
}
