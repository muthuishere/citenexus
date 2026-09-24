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
			[]citedClaim{{text: "One fact.", cited: []string{"a"}}, {text: "Two fact.", cited: []string{"b"}}}},
		{"marker after period attaches backwards", "One fact. [eu:a] Two fact. [eu:b]",
			[]citedClaim{{text: "One fact.", cited: []string{"a"}}, {text: "Two fact.", cited: []string{"b"}}}},
		{"dotted id does not split", "One fact [eu:doc.pdf#3].",
			[]citedClaim{{text: "One fact.", cited: []string{"doc.pdf#3"}}}},
		{"comma list and repeated groups", "One fact [eu:a, eu:b][eu:c, a].",
			[]citedClaim{{text: "One fact.", cited: []string{"a", "b", "c"}}}},
		{"uncited", "One fact.", []citedClaim{{text: "One fact.", cited: nil}}},
		{"facet markers are separate from citations", "One fact [eu:a][q:cost]. Two fact [q:when, q:who][eu:b].",
			[]citedClaim{{text: "One fact.", cited: []string{"a"}, facets: []string{"cost"}},
				{text: "Two fact.", cited: []string{"b"}, facets: []string{"when", "who"}}}},
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
	if res.Evidence.Decision != result.DecisionPartial || res.Answer != "The notice period is 30 days." {
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

func TestGuardsCannotBeOverriddenByTheModel(t *testing.T) {
	// The checker is sure of everything; only the guards stand in the way.
	sure := &fakeChecker{scores: map[string][2]float64{dutchLeave.Text: {0.99, 0.0}}}
	opts := VerifyOptions{Checker: sure, AnswerLanguage: "en"}
	cases := map[string]string{
		"number":   "Employees get 30 vacation days a year [eu:nl-1#0].",
		"negation": "Employees do not get 25 vacation days a year [eu:nl-1#0].",
		"name":     "Employees at Acme get 25 vacation days a year [eu:nl-1#0].",
	}
	for guard, claim := range cases {
		t.Run(guard, func(t *testing.T) {
			res := verify(t, claim, []EvidenceUnit{dutchLeave}, opts)
			if res.Evidence.Decision != result.DecisionRefused || !strings.HasPrefix(res.Claims[0].Reason, guard+" guard") {
				t.Fatalf("%s guard did not hold: %+v", guard, res.Claims)
			}
		})
	}
}

func TestNumberGuardReadsEachSideInItsLanguage(t *testing.T) {
	cases := []struct {
		claim, claimLang, passage, passageLang string
		pass                                   bool
	}{
		{"The fee is €25.50.", "en", "De vergoeding is € 25,50.", "nl", true},
		{"The budget is €1,500.", "en", "Het budget is € 1.500.", "nl", true},
		{"De vergoeding is € 25,-.", "nl", "De vergoeding is € 25,00.", "nl", true},
		{"The fee is €25.05.", "en", "De vergoeding is € 25,50.", "nl", false},
		{"The budget is €1.500.", "en", "Het budget is € 1.500.", "nl", false}, // 1.5 vs 1500
		{"Het budget is € 1.500.", "", "Het budget is € 1500.", "nl", false},   // undeclared claim: ambiguous
	}
	for _, c := range cases {
		got := numberGuard(c.claim, c.claimLang, c.passage, c.passageLang) == ""
		if got != c.pass {
			t.Errorf("%q (%s) over %q (%s): pass=%v, want %v", c.claim, c.claimLang, c.passage, c.passageLang, got, c.pass)
		}
	}
}

func TestNames(t *testing.T) {
	got := names("Employees at Acme get the CAO bonus per R-119. Then Payroll pays.")
	want := []string{"Acme", "CAO", "R-119", "Payroll"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
}

func TestQuotePathAnchorsTheContent(t *testing.T) {
	fee := EvidenceUnit{ID: "faq#7", DocumentID: "faq", Language: "nl",
		Text: "Voor thuiswerken geldt een vergoeding van € 25 exclusief btw per maand."}
	checker := &fakeChecker{scores: map[string][2]float64{fee.Text: {0.95, 0.01}}}
	opts := VerifyOptions{Checker: checker, CheckerName: "nli", AnswerLanguage: "nl"}

	// Same language, paraphrased framing, verbatim quote: admitted via the quote.
	res := verify(t, `Bij thuiswerk geldt "een vergoeding van € 25 exclusief btw" [eu:faq#7].`, []EvidenceUnit{fee}, opts)
	if res.Claims[0].VerifiedBy != "quote+model:nli" {
		t.Fatalf("quote path not taken: %+v", res.Claims)
	}
	// A quote that is not in the passage anchors nothing — and without
	// AdmitParaphrase the model cannot rescue a same-language claim.
	res = verify(t, `Er geldt "een vergoeding van € 25 inclusief btw" [eu:faq#7].`, []EvidenceUnit{fee}, opts)
	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("a fabricated quote was admitted: %+v", res.Claims)
	}
	// Without a checker the quote alone admits nothing.
	res = verify(t, `Bij thuiswerk geldt "een vergoeding van € 25 exclusief btw" [eu:faq#7].`, []EvidenceUnit{fee},
		VerifyOptions{AnswerLanguage: "nl"})
	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("quote admitted without a checker: %+v", res.Claims)
	}
}

func TestAdmitParaphraseIsOptIn(t *testing.T) {
	checker := &fakeChecker{scores: map[string][2]float64{leave.Text: {0.97, 0.01}}}
	claim := "Staff get 25 days of annual leave [eu:hr-3#0]."
	opts := VerifyOptions{Checker: checker, CheckerName: "nli", AnswerLanguage: "en"}
	if res := verify(t, claim, []EvidenceUnit{leave}, opts); res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("paraphrase admitted without opt-in: %+v", res.Claims)
	}
	opts.AdmitParaphrase = true
	res := verify(t, claim, []EvidenceUnit{leave}, opts)
	if res.Evidence.Decision != result.DecisionAnswered || res.Claims[0].VerifiedBy != "model:nli" {
		t.Fatalf("opted-in paraphrase not admitted: %+v", res.Claims)
	}
}

func TestMissingFacetsAreNamed(t *testing.T) {
	opts := VerifyOptions{Facets: []Facet{{ID: "notice", Label: "the notice period"}, {ID: "leave", Label: "annual leave"}}}
	ev := []EvidenceUnit{notice30, leave}

	res := verify(t, "The notice period is 30 days [eu:hr-1#0][q:notice]. Employees receive 40 days of annual leave [eu:hr-3#0][q:leave].", ev, opts)
	if res.Evidence.Decision != result.DecisionPartial || !reflect.DeepEqual(res.Evidence.MissingFacets, []string{"leave"}) {
		t.Fatalf("%s %v", res.Evidence.Decision, res.Evidence.MissingFacets)
	}
	if !strings.Contains(strings.Join(res.MissingEvidence, "|"), "no verified answer for: annual leave") {
		t.Fatalf("facet not named: %v", res.MissingEvidence)
	}

	res = verify(t, "The notice period is 30 days [eu:hr-1#0][q:notice]. Employees receive 25 days of annual leave [eu:hr-3#0][q:leave].", ev, opts)
	if res.Evidence.Decision != result.DecisionAnswered || res.Evidence.MissingFacets != nil {
		t.Fatalf("complete answer marked incomplete: %+v", res.Evidence)
	}
}

func TestClauseFinalNegationIsNotDropped(t *testing.T) {
	parking := EvidenceUnit{ID: "p#1", DocumentID: "p", Language: "nl",
		Text: "De werkgever vergoedt de parkeerkosten niet. Reiskosten worden wel vergoed."}
	// The shared predicate accepts the dropped negation — the hole this closes.
	if !gateAccepts("De werkgever vergoedt de parkeerkosten.", parking.Text) {
		t.Skip("the ADR-0009 predicate now catches this itself; the guard is redundant")
	}
	sure := &fakeChecker{scores: map[string][2]float64{parking.Text: {0.99, 0.0}}}
	for _, opts := range []VerifyOptions{{}, {Checker: sure, AdmitParaphrase: true, AnswerLanguage: "nl"}} {
		res := verify(t, "De werkgever vergoedt de parkeerkosten [eu:p#1].", []EvidenceUnit{parking}, opts)
		if res.Evidence.Decision != result.DecisionRefused || !strings.HasPrefix(res.Claims[0].Reason, "negation guard") {
			t.Fatalf("dropped clause-final niet admitted (checker=%v): %+v", opts.Checker != nil, res.Claims)
		}
	}
	// The negated claim itself, and a claim from the next clause, still pass.
	res := verify(t, "De werkgever vergoedt de parkeerkosten niet [eu:p#1]. Reiskosten worden vergoed [eu:p#1].",
		[]EvidenceUnit{parking}, VerifyOptions{})
	if res.Evidence.Decision != result.DecisionAnswered {
		t.Fatalf("true claims refused: %+v", res.Claims)
	}
}

func TestNextClauseNegationDoesNotRefuse(t *testing.T) {
	ev := EvidenceUnit{ID: "c#1", DocumentID: "c", Language: "nl",
		Text: "De werkgever vergoedt de parkeerkosten, maar niet de reiskosten."}
	res := verify(t, "De werkgever vergoedt de parkeerkosten [eu:c#1].", []EvidenceUnit{ev}, VerifyOptions{})
	if res.Evidence.Decision != result.DecisionAnswered {
		t.Fatalf("a negation in the next clause refused a true claim: %+v", res.Claims)
	}
}

func TestR119R120InclExclBtw(t *testing.T) {
	faq := EvidenceUnit{ID: "R-119", DocumentID: "hr-faq", Language: "nl",
		Text:      "Voor thuiswerken geldt een vergoeding van € 25 exclusief btw per maand.",
		Authority: map[string]string{"source_layer": "adopted"}}
	note := EvidenceUnit{ID: "R-120", DocumentID: "voorgesteld-beleid", Language: "nl",
		Text:      "Voor thuiswerken geldt een vergoeding van € 25 inclusief btw per maand.",
		Authority: map[string]string{"source_layer": "proposal"}}
	claim := "Voor thuiswerken geldt een vergoeding van € 25 exclusief btw per maand [eu:R-119]."

	// Untiered: the disagreement is surfaced and the claim abstains, citing both.
	res := verify(t, claim, []EvidenceUnit{faq, note}, VerifyOptions{AnswerLanguage: "nl"})
	if res.Answer != result.ConflictRefusalAnswer || len(res.Sources) != 2 ||
		!strings.HasPrefix(res.Conflicts[0], "inclusion:") {
		t.Fatalf("untiered: %q %v %v", res.Answer, res.Conflicts, res.Sources)
	}

	// Tiered at ingest: the adopted FAQ outranks the proposal note.
	policy := authority.Ordered([]string{"proposal", "adopted"}, "").WithKey("source_layer")
	res = verify(t, claim, []EvidenceUnit{faq, note}, VerifyOptions{AnswerLanguage: "nl", Authority: policy})
	if res.Evidence.Decision != result.DecisionAnswered || !strings.Contains(res.Conflicts[0], "resolved by authority") {
		t.Fatalf("tiered: %s %v", res.Evidence.Decision, res.Conflicts)
	}
}

// A non-nil empty LeadInFrames disables the content-free rule: every ":" lead-in
// is joined again, so "Zo zit het" lands in the claim and the gate refuses it.
func TestLeadInFramesEmptyDisablesTheRule(t *testing.T) {
	ev := []EvidenceUnit{{ID: "a", DocumentID: "a", Language: "nl", Text: "De werknemer heeft recht op 25 vakantiedagen per kalenderjaar."}}
	answer := "Zo zit het:\n- De werknemer heeft recht op 25 vakantiedagen per kalenderjaar [eu:a]"
	res, err := VerifyAnswer(context.Background(), answer, ev, VerifyOptions{AnswerLanguage: "nl", LeadInFrames: []string{}})
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Claims) != 1 || res.Claims[0].Supported || !strings.HasPrefix(res.Claims[0].Claim, "Zo zit het") {
		t.Fatalf("empty frames must join the lead-in: %+v", res.Claims)
	}
}
