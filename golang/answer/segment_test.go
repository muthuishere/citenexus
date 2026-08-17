package answer

import (
	"reflect"
	"sort"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// expectedSegmentationCases pins the size of conformance/cases/segmentation.json.
// The per-case loop below is a contract only while the case list cannot shrink.
const expectedSegmentationCases = 95

func TestSegmentationVectorCount(t *testing.T) {
	var cases []struct {
		Text   string   `json:"text"`
		Claims []string `json:"claims"`
	}
	conform.Case(t, "segmentation.json", &cases)
	if len(cases) != expectedSegmentationCases {
		t.Fatalf("segmentation.json: got %d cases, want %d", len(cases), expectedSegmentationCases)
	}
}

// TestSplitClaimsConformance is the ADR-0009 segmentation contract: every case
// in conformance/cases/segmentation.json must split exactly as the Python
// reference does — abbreviations, initials, decimals, terminator runs, CJK
// terminators, and the hard-newline rule.
func TestSplitClaimsConformance(t *testing.T) {
	var cases []struct {
		Text   string   `json:"text"`
		Claims []string `json:"claims"`
	}
	conform.Case(t, "segmentation.json", &cases)

	if len(cases) != expectedSegmentationCases {
		t.Fatalf("segmentation.json: got %d cases, want %d", len(cases), expectedSegmentationCases)
	}
	for _, c := range cases {
		got := SplitClaims(c.Text)
		want := c.Claims
		if want == nil {
			want = []string{}
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("SplitClaims(%q)\n got  %q\n want %q", c.Text, got, want)
		}
	}
}

// TestSegmentationTableMatchesConformance pins the embedded copy to the
// canonical conformance/segmentation.json (ADR-0010 tier 2).
func TestSegmentationTableMatchesConformance(t *testing.T) {
	var canonical struct {
		Terminators   []string `json:"terminators"`
		Abbreviations []string `json:"abbreviations"`
	}
	conform.Data(t, "segmentation.json", &canonical)

	terms, abbrevs := loadSegmentationTable()

	gotTerms := make([]string, 0, len(terms))
	for r := range terms {
		gotTerms = append(gotTerms, string(r))
	}
	gotAbbrevs := make([]string, 0, len(abbrevs))
	for a := range abbrevs {
		gotAbbrevs = append(gotAbbrevs, a)
	}
	wantTerms := append([]string{}, canonical.Terminators...)
	wantAbbrevs := append([]string{}, canonical.Abbreviations...)
	for _, s := range []*[]string{&gotTerms, &gotAbbrevs, &wantTerms, &wantAbbrevs} {
		sort.Strings(*s)
	}
	if !reflect.DeepEqual(gotTerms, wantTerms) {
		t.Errorf("embedded terminators diverged:\n got  %q\n want %q", gotTerms, wantTerms)
	}
	if !reflect.DeepEqual(gotAbbrevs, wantAbbrevs) {
		t.Errorf("embedded abbreviations diverged:\n got  %q\n want %q", gotAbbrevs, wantAbbrevs)
	}
}

// TestSplitClaimsIsCodePointIndexed guards the Go-specific trap: Python indexes
// strings by code point, so the scanner must run over runes, not bytes. A
// byte-indexed scanner mangles multi-byte terminators.
func TestSplitClaimsIsCodePointIndexed(t *testing.T) {
	got := SplitClaims("従業員は開示してはならない。期間は五年である。")
	want := []string{"従業員は開示してはならない。", "期間は五年である。"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("CJK split\n got  %q\n want %q", got, want)
	}
}
