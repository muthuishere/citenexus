package answer

import (
	"testing"

	"github.com/muthuishere/citenexus/golang/result"
)

// End-to-end proof that ADR-0007 conflict surfacing is WIRED, not merely ported.
//
// Before this change golang/answer/askwith.go hardcoded `Conflicts: []string{}`
// and never set ConflictsDetected, so the Go port would confidently answer the
// restated-filing corpus from whichever passage happened to rank first — the
// exact defect ADR-0007 closes. Python already abstains here; these tests hold
// Go to the same behaviour.

const (
	dividendQuestion = "What was the dividend per share for the period?"
	dividend12       = "The dividend for the period was 12 cents per share."
	dividend30       = "The dividend for the period was 30 cents per share."
)

// TestAskAbstainsOnContradictoryFilings: two filings of the same period give
// different dividends. Strict mode refuses AND cites both sides.
func TestAskAbstainsOnContradictoryFilings(t *testing.T) {
	corpus := []Doc{
		{DocumentID: "filing-q1", Text: dividend12},
		{DocumentID: "filing-q1-restated", Text: dividend30},
	}
	res := Ask(corpus, dividendQuestion, DefaultTopK)

	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("decision = %q, want refused (answer was %q)", res.Evidence.Decision, res.Answer)
	}
	if res.Answer != result.ConflictRefusalAnswer {
		t.Fatalf("answer = %q, want %q", res.Answer, result.ConflictRefusalAnswer)
	}
	if res.Evidence.ConflictsDetected != 1 {
		t.Fatalf("conflicts_detected = %d, want 1", res.Evidence.ConflictsDetected)
	}
	// Both documents cited: a refusal that hides the evidence is only marginally
	// better than a confident pick.
	cited := map[string]string{}
	for _, s := range res.Sources {
		cited[s.Document] = s.Passage
	}
	if len(cited) != 2 || cited["filing-q1"] != dividend12 || cited["filing-q1-restated"] != dividend30 {
		t.Fatalf("sources = %+v, want both filings cited verbatim", res.Sources)
	}
	if len(res.Conflicts) != 1 {
		t.Fatalf("conflicts = %q, want one line", res.Conflicts)
	}
	if len(res.MissingEvidence) != 1 ||
		res.MissingEvidence[0] != "cited sources disagree and the conflict is unresolved" {
		t.Fatalf("missing_evidence = %q", res.MissingEvidence)
	}
	if len(res.Claims) != 0 {
		t.Fatalf("claims = %+v, want none on an abstention", res.Claims)
	}
	t.Logf("conflict line: %q", res.Conflicts[0])
}

// TestAskAnswersWhenDifferingNumbersAreNotAConflict is the other half of the
// contract, and the one that actually matters: MAX_RESIDUAL. Two DIFFERENT
// quarters legitimately carry different dividends — the extra content token
// ("q1" vs "q2") is what makes them complementary, and a port that treated every
// numeric difference as a conflict would turn this into a false refusal.
func TestAskAnswersWhenDifferingNumbersAreNotAConflict(t *testing.T) {
	corpus := []Doc{
		{DocumentID: "filing-q1", Text: "The Q1 dividend was 12 cents per share."},
		{DocumentID: "filing-q2", Text: "The Q2 dividend was 15 cents per share."},
	}
	res := Ask(corpus, "What was the Q1 dividend per share?", DefaultTopK)

	if res.Evidence.Decision != result.DecisionAnswered {
		t.Fatalf("decision = %q, want answered (answer %q, conflicts %q)",
			res.Evidence.Decision, res.Answer, res.Conflicts)
	}
	if res.Evidence.ConflictsDetected != 0 {
		t.Fatalf("conflicts_detected = %d, want 0", res.Evidence.ConflictsDetected)
	}
	if len(res.Conflicts) != 0 {
		t.Fatalf("conflicts = %q, want none", res.Conflicts)
	}
	t.Logf("answer: %q from %s", res.Answer, res.Sources[0].Document)
}

// TestAskIsUnchangedWithoutConflict: a single-document corpus answers exactly as
// it did before conflict detection existed. Wiring a new abstention path must
// not move any Result that has nothing to abstain over.
func TestAskIsUnchangedWithoutConflict(t *testing.T) {
	corpus := []Doc{{DocumentID: "policy", Text: dividend12}}
	res := Ask(corpus, dividendQuestion, DefaultTopK)
	if res.Evidence.Decision != result.DecisionAnswered || res.Evidence.ConflictsDetected != 0 {
		t.Fatalf("decision %q conflicts %d, want answered/0", res.Evidence.Decision, res.Evidence.ConflictsDetected)
	}
	if len(res.Conflicts) != 0 {
		t.Fatalf("conflicts = %q, want none", res.Conflicts)
	}
}

// TestAskAbstainsOnClonedContradiction proves the two halves compose: the
// restated filing is duplicated under a third id, so near-duplicate collapse
// must NOT make the contradiction disappear (conflict is checked before
// duplication) and SupportingSources must count the clone once.
func TestAskAbstainsOnClonedContradiction(t *testing.T) {
	corpus := []Doc{
		{DocumentID: "filing-q1", Text: dividend12},
		{DocumentID: "filing-q1-restated", Text: dividend30},
		{DocumentID: "filing-q1-restated-mirror", Text: dividend30},
	}
	res := Ask(corpus, dividendQuestion, DefaultTopK)
	if res.Evidence.Decision != result.DecisionRefused {
		t.Fatalf("decision = %q, want refused", res.Evidence.Decision)
	}
	if res.Evidence.SupportingSources != 2 {
		t.Fatalf("supporting_sources = %d, want 2 (the mirror collapses)", res.Evidence.SupportingSources)
	}
	t.Logf("conflicts_detected=%d conflicts=%q sources=%d",
		res.Evidence.ConflictsDetected, res.Conflicts, len(res.Sources))
}
