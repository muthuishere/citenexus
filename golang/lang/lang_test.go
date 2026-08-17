package lang

import (
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// Proven against the shared fixture: every §11a fallback case must match the
// Python reference resolve_answer_language exactly, no leniency.
// expectedLanguageCases pins the size of conformance/cases/language.json.
const expectedLanguageCases = 6

func TestLanguageVectorCount(t *testing.T) {
	var cases []struct {
		Name string `json:"name"`
	}
	conform.Case(t, "language.json", &cases)
	if len(cases) != expectedLanguageCases {
		t.Fatalf("language.json: got %d cases, want %d", len(cases), expectedLanguageCases)
	}
}

func TestResolveAnswerLanguageConformance(t *testing.T) {
	var cases []struct {
		Name                 string     `json:"name"`
		Detection            *Detection `json:"detection"`
		AnswerLanguage       string     `json:"answer_language"`
		ConversationLanguage string     `json:"conversation_language"`
		LanguagesInEvidence  []string   `json:"languages_in_evidence"`
		DefaultAnswerLang    string     `json:"default_answer_language"`
		Expected             string     `json:"expected"`
	}
	conform.Case(t, "language.json", &cases)

	if len(cases) != expectedLanguageCases {
		t.Fatalf("language.json: got %d cases, want %d", len(cases), expectedLanguageCases)
	}
	for _, c := range cases {
		got := ResolveAnswerLanguage(
			c.Detection,
			c.AnswerLanguage,
			c.ConversationLanguage,
			c.LanguagesInEvidence,
			c.DefaultAnswerLang,
		)
		if got != c.Expected {
			t.Errorf("%s: ResolveAnswerLanguage = %q, want %q", c.Name, got, c.Expected)
		}
	}
}
