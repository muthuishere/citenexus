package lang

import (
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// The named code sets are pinned to conformance/cases/languages.json, which the
// Python reference generates. Python, Go and JS each assert against the same
// file, so the 41 codes cannot diverge by review error — the same three-way pin
// the ADR-0011 script CLAIM already has in tokenize_v2_test.go.

type languagesFixture struct {
	AutoSentinel      string   `json:"auto_sentinel"`
	Scripts           []string `json:"scripts"`
	SupportedScripts  []string `json:"supported_scripts"`
	ContinuousScripts []string `json:"continuous_scripts"`
	Languages         []struct {
		Code      string   `json:"code"`
		Name      string   `json:"name"`
		Scripts   []string `json:"scripts"`
		Supported bool     `json:"supported"`
	} `json:"languages"`
}

func loadLanguages(t *testing.T) languagesFixture {
	t.Helper()
	var f languagesFixture
	conform.Case(t, "languages.json", &f)
	return f
}

// expectedLanguagesCounts pins every list in conformance/cases/languages.json.
// The row-by-row loop below compares the table against the fixture, so a fixture
// that lost rows would agree with a table that lost the same rows unless the
// absolute sizes are pinned too.
var expectedLanguagesCounts = map[string]int{
	"scripts":            27,
	"supported_scripts":  14,
	"continuous_scripts": 7,
	"languages":          41,
}

func TestLanguagesVectorBucketSizes(t *testing.T) {
	f := loadLanguages(t)
	for name, got := range map[string]int{
		"scripts":            len(f.Scripts),
		"supported_scripts":  len(f.SupportedScripts),
		"continuous_scripts": len(f.ContinuousScripts),
		"languages":          len(f.Languages),
	} {
		if want := expectedLanguagesCounts[name]; got != want {
			t.Errorf("languages.json bucket %q: got %d entries, want %d", name, got, want)
		}
	}
}

func TestSearchLanguageTableMatchesConformance(t *testing.T) {
	f := loadLanguages(t)
	got := SearchLanguages()
	if len(got) != len(f.Languages) {
		t.Fatalf("table has %d languages, fixture has %d", len(got), len(f.Languages))
	}
	for i, want := range f.Languages {
		g := got[i]
		if string(g.Code) != want.Code || g.Name != want.Name || g.Supported != want.Supported {
			t.Errorf("row %d = {%s %s %v}, want {%s %s %v}",
				i, g.Code, g.Name, g.Supported, want.Code, want.Name, want.Supported)
		}
		scripts := make([]string, len(g.Scripts))
		for j, s := range g.Scripts {
			scripts[j] = string(s)
		}
		if !reflect.DeepEqual(scripts, want.Scripts) {
			t.Errorf("row %d scripts = %v, want %v", i, scripts, want.Scripts)
		}
	}
}

func TestAutoSentinelMatchesConformance(t *testing.T) {
	f := loadLanguages(t)
	if f.AutoSentinel != string(Auto) {
		t.Fatalf("Auto = %q, want %q", Auto, f.AutoSentinel)
	}
	if f.AutoSentinel != AutoAnswerLanguage {
		t.Fatalf("AutoAnswerLanguage = %q, want %q", AutoAnswerLanguage, f.AutoSentinel)
	}
	// The sentinel is NOT a searchable language.
	if _, ok := SearchLanguageByCode(Auto); ok {
		t.Fatal("the auto sentinel must not be in the search-language table")
	}
}

// TestPlainStringsStillAssign is the compatibility pin: Language and Script are
// DEFINED STRING TYPES, so an untyped constant converts implicitly and every
// pre-existing literal call site keeps compiling. If someone ever "improves"
// these into an iota enum, this stops building.
func TestPlainStringsStillAssign(t *testing.T) {
	var l Language = "ta"
	var s Script = "tamil"
	if l != Tamil || s != ScriptTamil {
		t.Fatalf("literal assignment diverged: %q %q", l, s)
	}
	if got := ResolveAnswerLanguage(nil, "ta", "", nil, "en"); got != "ta" {
		t.Fatalf("string answer language = %q, want %q", got, "ta")
	}
	if got := ResolveAnswerLanguage(nil, string(Tamil), "", nil, string(English)); got != string(Tamil) {
		t.Fatalf("member answer language = %q, want %q", got, Tamil)
	}
}

func TestLookupByCodeAcceptsAPlainString(t *testing.T) {
	byString, ok := SearchLanguageByCode("ta")
	if !ok {
		t.Fatal(`SearchLanguageByCode("ta") not found`)
	}
	byMember, ok := SearchLanguageByCode(Tamil)
	if !ok {
		t.Fatal("SearchLanguageByCode(Tamil) not found")
	}
	if !reflect.DeepEqual(byString, byMember) {
		t.Fatalf("string and member lookups differ: %+v vs %+v", byString, byMember)
	}
	if _, ok := SearchLanguageByCode("tamiil"); ok {
		t.Fatal("a typo must not resolve — codes are never guessed")
	}
}

// Every script the table names must be a declared Script constant, and every
// declared Script must appear in the fixture's script list.
func TestScriptConstantsMatchConformance(t *testing.T) {
	f := loadLanguages(t)
	declared := map[string]bool{}
	for _, s := range f.Scripts {
		declared[s] = true
	}
	for _, l := range SearchLanguages() {
		for _, s := range l.Scripts {
			if !declared[string(s)] {
				t.Errorf("%s names script %q, absent from the fixture", l.Code, s)
			}
		}
	}
	if len(f.Scripts) == 0 || !declared[string(ScriptLatin)] || !declared[string(ScriptUnknown)] {
		t.Fatal("fixture script list is missing latin/unknown")
	}
}
