package answer

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/muthuishere/citenexus/golang/authority"
	"github.com/muthuishere/citenexus/golang/result"
)

var notice30 = EvidenceUnit{ID: "hr-1#0", DocumentID: "hr-1", Text: "The notice period is 30 days.", Language: "en"}
var notice60 = EvidenceUnit{ID: "hr-2#0", DocumentID: "hr-2", Text: "The notice period is 60 days.", Language: "en"}
var leave = EvidenceUnit{ID: "hr-3#0", DocumentID: "hr-3", Text: "Employees receive 25 days of annual leave.", Language: "en"}
var dutchLeave = EvidenceUnit{ID: "nl-1#0", DocumentID: "nl-1", Text: "Werknemers krijgen 25 vakantiedagen per jaar.", Language: "nl"}

// fakeChecker answers from a table keyed by passage; unknown passages score (0, 0).
type fakeChecker struct {
	scores map[string][2]float64
	err    error
	calls  int
}

func (f *fakeChecker) Check(_ context.Context, _ string, passage string) (float64, float64, error) {
	f.calls++
	if f.err != nil {
		return 0, 0, f.err
	}
	s := f.scores[passage]
	return s[0], s[1], nil
}

func verify(t *testing.T, answer string, evidence []EvidenceUnit, opts VerifyOptions) result.Result {
	t.Helper()
	res, err := VerifyAnswer(context.Background(), answer, evidence, opts)
	if err != nil {
		t.Fatalf("VerifyAnswer: %v", err)
	}
	return res
}

func TestParseCitations(t *testing.T) {
	cases := []struct {
		name   string
		answer string
		want   []citedClaim
	}{
		{"marker before period", "One fact [eu:a]. Two fact [eu:b].",
			[]citedClaim{{"One fact.", []string{"a"}}, {"Two fact.", []string{"b"}}}},
		{"marker after period attaches backwards", "One fact. [eu:a] Two fact. [eu:b]",
			[]citedClaim{{"One fact.", []string{"a"}}, {"Two fact.", []string{"b"}}}},
		{"dotted id does not split", "One fact [eu:doc.pdf#3].",
			[]citedClaim{{"One fact.", []string{"doc.pdf#3"}}}},
		{"comma list and repeated groups", "One fact [eu:a, eu:b][eu:c, a].",
			[]citedClaim{{"One fact.", []string{"a", "b", "c"}}}},
		{"uncited", "One fact.", []citedClaim{{"One fact.", nil}}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := parseCitations(c.answer); !reflect.DeepEqual(got, c.want) {
				t.Fatalf("got %#v, want %#v", got, c.want)
			}
		})
	}
}

func TestVerifyAnswerKeepsTheTrueHalf(t *testing.T) {
	res := verify(t, "The notice period is 30 days [eu:hr-1#0]. The notice period is 90 days [eu:hr-1#0].",
		[]EvidenceUnit{notice30, leave}, VerifyOptions{})
	if res.Evidence.Decision != result.DecisionAnswered || res.Answer != "The notice period is 30 days." {
		t.Fatalf("got %q / %s", res.Answer, res.Evidence.Decision)
	}
	if res.Evidence.AllClaimsVerified || res.Evidence.UnsupportedClaimsRemoved != 1 {
		t.Fatalf("drop not reported: %+v", res.Evidence)
	}
	if res.Claims[0].VerifiedBy != "gate" || res.Claims[1].Reason != ReasonNotSupported {
		t.Fatalf("claims: %+v", res.Claims)
	}
	if len(res.Sources) != 1 || res.Sources[0].Document != "hr-1" {
		t.Fatalf("sources: %+v", res.Sources)
	}
}

func TestVerifyAnswerCitationRules(t *testing.T) {
	ev := []EvidenceUnit{notice30, leave}
	t.Run("unknown id", func(t *testing.T) {
		res := verify(t, "The notice period is 30 days [eu:nope].", ev, VerifyOptions{})
		if res.Evidence.Decision != result.DecisionRefused || res.Claims[0].Reason != ReasonUnknownCitation {
			t.Fatalf("%+v", res.Claims)
		}
	})
	t.Run("wrong citation is not rescued by another unit", func(t *testing.T) {
		res := verify(t, "The notice period is 30 days [eu:hr-3#0].", ev, VerifyOptions{})
		if res.Evidence.Decision != result.DecisionRefused {
			t.Fatalf("a claim citing the wrong unit must not pass: %+v", res.Claims)
		}
	})
	t.Run("uncited is searched by default", func(t *testing.T) {
		res := verify(t, "The notice period is 30 days.", ev, VerifyOptions{})
		if res.Evidence.Decision != result.DecisionAnswered || res.Claims[0].Sources[0] != "hr-1#0" {
			t.Fatalf("%+v", res.Claims)
		}
	})
	t.Run("uncited is dropped when citations are required", func(t *testing.T) {
		res := verify(t, "The notice period is 30 days.", ev, VerifyOptions{RequireCitations: true})
		if res.Evidence.Decision != result.DecisionRefused || res.Claims[0].Reason != ReasonUncited {
			t.Fatalf("%+v", res.Claims)
		}
	})
	t.Run("empty answer refuses", func(t *testing.T) {
		res := verify(t, "  ", ev, VerifyOptions{})
		if res.Evidence.Decision != result.DecisionRefused {
			t.Fatalf("%+v", res)
		}
	})
}

func TestVerifyAnswerInvalidEvidenceIsAnError(t *testing.T) {
	for _, ev := range [][]EvidenceUnit{{notice30, notice30}, {{Text: "x"}}} {
		if _, err := VerifyAnswer(context.Background(), "x", ev, VerifyOptions{}); !errors.Is(err, ErrInvalidEvidence) {
			t.Fatalf("want ErrInvalidEvidence, got %v", err)
		}
	}
}

func TestSupportCheckerVetoesAGateAdmittedClaim(t *testing.T) {
	checker := &fakeChecker{scores: map[string][2]float64{notice30.Text: {0.1, 0.8}}}
	res := verify(t, "The notice period is 30 days [eu:hr-1#0].", []EvidenceUnit{notice30},
		VerifyOptions{Checker: checker})
	if res.Evidence.Decision != result.DecisionRefused || res.Claims[0].Reason != ReasonContradicted {
		t.Fatalf("veto did not fire: %+v", res.Claims)
	}
}

func TestSupportCheckerAdmitsOnlyCrossLanguageClaims(t *testing.T) {
	checker := &fakeChecker{scores: map[string][2]float64{
		dutchLeave.Text: {0.97, 0.01},
		leave.Text:      {0.97, 0.01},
	}}
	opts := VerifyOptions{Checker: checker, CheckerName: "mdeberta", AnswerLanguage: "en"}

	res := verify(t, "Employees get 25 vacation days a year [eu:nl-1#0].", []EvidenceUnit{dutchLeave}, opts)
	if res.Evidence.Decision != result.DecisionAnswered || res.Claims[0].VerifiedBy != "model:mdeberta" {
		t.Fatalf("cross-language claim not admitted: %+v", res.Claims)
	}
	if res.Evidence.ModelVerifiedClaims != 1 {
		t.Fatalf("model admission not counted: %+v", res.Evidence)
	}

	// Same language: the checker's entailment must NOT rescue a gate failure.
	res = verify(t, "Staff get 25 vacation days a year [eu:hr-3#0].", []EvidenceUnit{leave}, opts)
	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("same-language claim admitted by the model: %+v", res.Claims)
	}

	// Undeclared answer language: no admission either.
	opts.AnswerLanguage = ""
	res = verify(t, "Employees get 25 vacation days a year [eu:nl-1#0].", []EvidenceUnit{dutchLeave}, opts)
	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("admitted without a declared answer language: %+v", res.Claims)
	}
}

func TestSupportCheckerBelowThresholdDoesNotAdmit(t *testing.T) {
	checker := &fakeChecker{scores: map[string][2]float64{dutchLeave.Text: {0.85, 0.01}}}
	res := verify(t, "Employees get 25 vacation days a year [eu:nl-1#0].", []EvidenceUnit{dutchLeave},
		VerifyOptions{Checker: checker, AnswerLanguage: "en-GB"})
	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("admitted below the default threshold: %+v", res.Claims)
	}
}

func TestSupportCheckerErrorIsAnError(t *testing.T) {
	checker := &fakeChecker{err: errors.New("onnx: boom")}
	_, err := VerifyAnswer(context.Background(), "The notice period is 30 days [eu:hr-1#0].",
		[]EvidenceUnit{notice30}, VerifyOptions{Checker: checker})
	if err == nil || !strings.Contains(err.Error(), "boom") {
		t.Fatalf("want checker error, got %v", err)
	}
}

func TestEqualAuthorityConflictAbstainsCitingBothSides(t *testing.T) {
	res := verify(t, "The notice period is 30 days [eu:hr-1#0].", []EvidenceUnit{notice30, notice60}, VerifyOptions{})
	if res.Answer != result.ConflictRefusalAnswer || res.Evidence.ConflictsDetected != 1 {
		t.Fatalf("got %q, %+v", res.Answer, res.Evidence)
	}
	if len(res.Sources) != 2 || res.Claims[0].Reason != ReasonUnresolvedClaims {
		t.Fatalf("both sides not cited: %+v / %+v", res.Sources, res.Claims)
	}
}

func TestHigherAuthorityResolvesTheConflict(t *testing.T) {
	adopted, proposal := notice30, notice60
	adopted.Authority = map[string]string{"authority_tier": "adopted"}
	proposal.Authority = map[string]string{"authority_tier": "proposal"}
	policy := authority.Ordered([]string{"proposal", "adopted"}, "")
	ev := []EvidenceUnit{proposal, adopted}

	res := verify(t, "The notice period is 30 days [eu:hr-1#0].", ev, VerifyOptions{Authority: policy})
	if res.Evidence.Decision != result.DecisionAnswered || res.Evidence.AuthorityTier != "adopted" {
		t.Fatalf("adopted claim should stand: %q %+v", res.Answer, res.Evidence)
	}
	if len(res.Conflicts) != 1 || !strings.Contains(res.Conflicts[0], "resolved by authority") {
		t.Fatalf("conflict not surfaced: %v", res.Conflicts)
	}

	res = verify(t, "The notice period is 60 days [eu:hr-2#0].", ev, VerifyOptions{Authority: policy})
	if res.Evidence.Decision != result.DecisionRefused || res.Claims[0].Reason != ReasonOutranked {
		t.Fatalf("proposal claim should be dropped: %+v", res.Claims)
	}
}

func TestAuthorityFloorExcludesCitedEvidence(t *testing.T) {
	note := leave
	note.Authority = map[string]string{"authority_tier": "note"}
	policy := authority.Ordered([]string{"note", "adopted"}, "adopted")
	res := verify(t, "Employees receive 25 days of annual leave [eu:hr-3#0].", []EvidenceUnit{note},
		VerifyOptions{Authority: policy})
	if res.Evidence.Decision != result.DecisionRefused || !res.Evidence.AuthorityFloorApplied {
		t.Fatalf("%+v", res.Evidence)
	}
	if res.Claims[0].Reason != ReasonBelowFloor || res.MissingEvidence[0] != authority.InsufficientAuthority {
		t.Fatalf("%+v / %v", res.Claims, res.MissingEvidence)
	}
}

func TestNewResultFieldsAreOmittedWhenEmpty(t *testing.T) {
	raw, err := json.Marshal(result.Claim{Claim: "x", Sources: []string{}})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), "verified_by") || strings.Contains(string(raw), "reason") {
		t.Fatalf("existing wire shape changed: %s", raw)
	}
}
