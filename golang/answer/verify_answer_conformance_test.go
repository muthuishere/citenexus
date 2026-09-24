package answer

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/result"
)

type verifyVector struct {
	Name            string              `json:"name"`
	MustRefuse      bool                `json:"must_refuse"`
	Answer          string              `json:"answer"`
	AnswerLanguage  string              `json:"answer_language"`
	AdmitParaphrase bool                `json:"admit_paraphrase"`
	NameAliases     map[string][]string `json:"name_aliases"`
	// Checker scores by premise: a unit id, or "a+b" for the union premise of a
	// list item joined to its lead-in (unionPremise). CheckerClaims overrides it
	// per claim text as the checker receives it (markup already stripped).
	Checker       map[string][]float64            `json:"checker"`
	CheckerClaims map[string]map[string][]float64 `json:"checker_claims"`
	LeadInFrames  []string                        `json:"lead_in_frames"`
	// Actors EXTENDS DefaultActorLexicon: actor id -> extra terms.
	Actors   map[string][]string `json:"actors"`
	Glossary [][2]string         `json:"glossary"`
	Evidence []struct {
		ID         string `json:"id"`
		DocumentID string `json:"document_id"`
		Language   string `json:"language"`
		Text       string `json:"text"`
	} `json:"evidence"`
	Expect struct {
		Decision          string `json:"decision"`
		ConflictsReported bool   `json:"conflicts_reported"`
		Claims            []struct {
			Supported bool   `json:"supported"`
			Reason    string `json:"reason"`
		} `json:"claims"`
	} `json:"expect"`
}

// idChecker scores by passage (a unit's text, or a union premise), and by
// (claim, passage) where a vector pins one claim.
type idChecker struct {
	byPassage map[string][2]float64
	byClaim   map[[2]string][2]float64
}

func (c idChecker) Check(_ context.Context, claim string, passage string) (float64, float64, error) {
	if s, ok := c.byClaim[[2]string{claim, passage}]; ok {
		return s[0], s[1], nil
	}
	s := c.byPassage[passage]
	return s[0], s[1], nil
}

func TestVerifyAnswerConformance(t *testing.T) {
	var file struct {
		Cases []verifyVector `json:"cases"`
	}
	// Go-owned until VerifyAnswer has a Python reference: conformance/ holds only
	// fixtures the Python generator produces (tests/test_conformance_fixtures.py).
	// Promote this file there when the Python port lands.
	raw, err := os.ReadFile("testdata/verify_answer.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(raw, &file); err != nil {
		t.Fatal(err)
	}
	if len(file.Cases) != 267 {
		t.Fatalf("verify_answer.json: got %d cases, want 267", len(file.Cases))
	}
	refuseControls := 0
	for _, c := range file.Cases {
		if c.MustRefuse {
			refuseControls++
		}
		t.Run(c.Name, func(t *testing.T) {
			evidence := make([]EvidenceUnit, len(c.Evidence))
			byID := map[string]EvidenceUnit{}
			for i, e := range c.Evidence {
				evidence[i] = EvidenceUnit{ID: e.ID, DocumentID: e.DocumentID, Language: e.Language, Text: e.Text}
				byID[e.ID] = evidence[i]
			}
			premise := func(key string) string {
				if a, b, union := strings.Cut(key, "+"); union {
					return unionPremise(byID[a], byID[b]).Text
				}
				return byID[key].Text
			}
			checker := idChecker{byPassage: map[string][2]float64{}, byClaim: map[[2]string][2]float64{}}
			for key, s := range c.Checker {
				checker.byPassage[premise(key)] = [2]float64{s[0], s[1]}
			}
			for key, claims := range c.CheckerClaims {
				for claim, s := range claims {
					checker.byClaim[[2]string{claim, premise(key)}] = [2]float64{s[0], s[1]}
				}
			}
			opts := VerifyOptions{AnswerLanguage: c.AnswerLanguage, AdmitParaphrase: c.AdmitParaphrase, NameAliases: c.NameAliases, LeadInFrames: c.LeadInFrames}
			opts.Glossary = c.Glossary
			if len(c.Actors) > 0 {
				lexicon := DefaultActorLexicon
				for id, terms := range c.Actors {
					lexicon = lexicon.With(id, terms...)
				}
				opts.Actors = &lexicon
			}
			if len(c.Checker) > 0 || len(c.CheckerClaims) > 0 {
				opts.Checker, opts.CheckerName = checker, "fake"
			}
			res, err := VerifyAnswer(context.Background(), c.Answer, evidence, opts)
			if err != nil {
				t.Fatal(err)
			}
			if string(res.Evidence.Decision) != c.Expect.Decision {
				t.Fatalf("decision %q, want %q; claims %+v", res.Evidence.Decision, c.Expect.Decision, res.Claims)
			}
			if c.Expect.ConflictsReported && len(res.Conflicts) == 0 {
				t.Fatalf("the conflict must still be REPORTED even when no claim is dropped for it")
			}
			if len(res.Claims) != len(c.Expect.Claims) {
				t.Fatalf("%d claims, want %d: %+v", len(res.Claims), len(c.Expect.Claims), res.Claims)
			}
			for i, want := range c.Expect.Claims {
				got := res.Claims[i]
				if got.Supported != want.Supported || !strings.HasPrefix(got.Reason, want.Reason) {
					t.Fatalf("claim %d: supported=%v reason=%q, want supported=%v reason prefix %q",
						i, got.Supported, got.Reason, want.Supported, want.Reason)
				}
			}
			if c.MustRefuse && res.Evidence.Decision == result.DecisionAnswered {
				t.Fatalf("must-refuse control was answered")
			}
		})
	}
	if refuseControls < 5 {
		t.Fatalf("only %d must-refuse controls; the guards need them to stay honest", refuseControls)
	}
}
