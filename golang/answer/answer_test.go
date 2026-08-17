package answer

import (
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// expectedE2ECounts pins the shape of conformance/cases/e2e_hermetic.json. Both
// answer_test.go and askwith_test.go drive this fixture; neither may run against
// a silently shrunken corpus or case list.
var expectedE2ECounts = map[string]int{
	"corpus": 3,
	"cases":  4,
	"top_k":  5,
}

func TestE2EHermeticVectorCounts(t *testing.T) {
	var fixture struct {
		Corpus []Doc `json:"corpus"`
		TopK   int   `json:"top_k"`
		Cases  []struct {
			Question string `json:"question"`
		} `json:"cases"`
	}
	conform.Case(t, "e2e_hermetic.json", &fixture)
	for name, got := range map[string]int{
		"corpus": len(fixture.Corpus),
		"cases":  len(fixture.Cases),
		"top_k":  fixture.TopK,
	} {
		if want := expectedE2ECounts[name]; got != want {
			t.Errorf("e2e_hermetic.json %q: got %d, want %d", name, got, want)
		}
	}
}

// eqOptStr compares an actual value (present flag + value) against an expected
// nullable string from the fixture.
func eqOptStr(present bool, got string, want *string) bool {
	if want == nil {
		return !present
	}
	return present && got == *want
}

// TestAskConformance drives the full cite-or-abstain flow over the pinned §7
// hermetic e2e fixture: build the corpus once, then for EACH question assert
// Ask() yields the expected decision, answer, document, passage, and eu_id.
// Follows the tokenize exemplar: assert over ALL cases, no leniency.
func TestAskConformance(t *testing.T) {
	var fixture struct {
		Corpus []Doc `json:"corpus"`
		TopK   int   `json:"top_k"`
		Cases  []struct {
			Question string `json:"question"`
			Expected struct {
				Decision string  `json:"decision"`
				Answer   string  `json:"answer"`
				Document *string `json:"document"`
				Passage  *string `json:"passage"`
				EuID     *string `json:"eu_id"`
			} `json:"expected"`
		} `json:"cases"`
	}
	conform.Case(t, "e2e_hermetic.json", &fixture)

	if len(fixture.Cases) != expectedE2ECounts["cases"] {
		t.Fatalf("e2e_hermetic.json: got %d cases, want %d", len(fixture.Cases), expectedE2ECounts["cases"])
	}
	if len(fixture.Corpus) != expectedE2ECounts["corpus"] {
		t.Fatalf("e2e_hermetic.json: got %d corpus docs, want %d", len(fixture.Corpus), expectedE2ECounts["corpus"])
	}
	if fixture.TopK != expectedE2ECounts["top_k"] {
		t.Fatalf("e2e_hermetic.json: top_k = %d, want %d", fixture.TopK, expectedE2ECounts["top_k"])
	}

	for _, c := range fixture.Cases {
		res := Ask(fixture.Corpus, c.Question, fixture.TopK)

		if string(res.Evidence.Decision) != c.Expected.Decision {
			t.Errorf("%q: decision = %q, want %q", c.Question, res.Evidence.Decision, c.Expected.Decision)
		}
		if res.Answer != c.Expected.Answer {
			t.Errorf("%q: answer = %q, want %q", c.Question, res.Answer, c.Expected.Answer)
		}

		var (
			docPresent, passPresent, euPresent bool
			gotDoc, gotPass, gotEu             string
		)
		if len(res.Sources) > 0 {
			docPresent, gotDoc = true, res.Sources[0].Document
			passPresent, gotPass = true, res.Sources[0].Passage
		}
		if len(res.Claims) > 0 && len(res.Claims[0].Sources) > 0 {
			euPresent, gotEu = true, res.Claims[0].Sources[0]
		}

		if !eqOptStr(docPresent, gotDoc, c.Expected.Document) {
			t.Errorf("%q: document = %v (present=%v), want %v", c.Question, gotDoc, docPresent, c.Expected.Document)
		}
		if !eqOptStr(passPresent, gotPass, c.Expected.Passage) {
			t.Errorf("%q: passage = %v (present=%v), want %v", c.Question, gotPass, passPresent, c.Expected.Passage)
		}
		if !eqOptStr(euPresent, gotEu, c.Expected.EuID) {
			t.Errorf("%q: eu_id = %v (present=%v), want %v", c.Question, gotEu, euPresent, c.Expected.EuID)
		}
	}
}
