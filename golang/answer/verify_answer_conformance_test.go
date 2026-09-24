package answer

import (
	"context"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
	"github.com/muthuishere/citenexus/golang/result"
)

type verifyVector struct {
	Name            string               `json:"name"`
	MustRefuse      bool                 `json:"must_refuse"`
	Answer          string               `json:"answer"`
	AnswerLanguage  string               `json:"answer_language"`
	AdmitParaphrase bool                 `json:"admit_paraphrase"`
	Checker         map[string][]float64 `json:"checker"`
	Evidence        []struct {
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

// idChecker scores by passage, from a table keyed by unit id.
type idChecker map[string][2]float64

func (c idChecker) Check(_ context.Context, _ string, passage string) (float64, float64, error) {
	s := c[passage]
	return s[0], s[1], nil
}

func TestVerifyAnswerConformance(t *testing.T) {
	var file struct {
		Cases []verifyVector `json:"cases"`
	}
	conform.Case(t, "verify_answer.json", &file)
	if len(file.Cases) != 12 {
		t.Fatalf("verify_answer.json: got %d cases, want 12", len(file.Cases))
	}
	refuseControls := 0
	for _, c := range file.Cases {
		if c.MustRefuse {
			refuseControls++
		}
		t.Run(c.Name, func(t *testing.T) {
			evidence := make([]EvidenceUnit, len(c.Evidence))
			checker := idChecker{}
			for i, e := range c.Evidence {
				evidence[i] = EvidenceUnit{ID: e.ID, DocumentID: e.DocumentID, Language: e.Language, Text: e.Text}
				if s, ok := c.Checker[e.ID]; ok {
					checker[e.Text] = [2]float64{s[0], s[1]}
				}
			}
			opts := VerifyOptions{AnswerLanguage: c.AnswerLanguage, AdmitParaphrase: c.AdmitParaphrase}
			if len(c.Checker) > 0 {
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
