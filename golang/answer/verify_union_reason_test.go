package answer

import (
	"context"
	"strings"
	"testing"
)

type lowChecker struct{}

func (lowChecker) Check(context.Context, string, string) (float64, float64, error) {
	return 0.1, 0.02, nil
}

// TestUnionReasonNamesAGuardOnlyWhenEveryPairFailedOne: a joined claim
// checked as a union of several (lead-in, item) pairs is refused by a GUARD
// only when every pair failed a guard. When any pair passed every guard and
// the checker would not admit it, the MODEL refused — whichever pair came
// first. The union reason used to be the first refused pair's.
func TestUnionReasonNamesAGuardOnlyWhenEveryPairFailedOne(t *testing.T) {
	evidence := []EvidenceUnit{
		{ID: "a1", DocumentID: "a1", Language: "nl", Text: "Artikel 7:13 BW regelt wanneer de werkgever een bedrag op het loon mag inhouden."},
		{ID: "a2", DocumentID: "a2", Language: "nl", Text: "Artikel 7:14 BW regelt wanneer de werkgever een bedrag op het loon mag inhouden."},
		{ID: "a3", DocumentID: "a3", Language: "nl", Text: "Artikel 7:15 BW regelt wanneer de werkgever een bedrag op het loon mag inhouden."},
		{ID: "b", DocumentID: "b", Language: "nl", Text: "De werkgever mag loon inhouden als de werknemer schade veroorzaakt."},
	}
	item := "\n- De werkgever mag loon inhouden als de werknemer schade veroorzaakt [eu:b]"
	for _, c := range []struct {
		name, lead string
		guard      bool
	}{
		{"guard-refused pair first, model-refused pair second", "Volgens artikel 7:13 BW [eu:a2][eu:a1]:", false},
		{"model-refused pair first, guard-refused pair second", "Volgens artikel 7:13 BW [eu:a1][eu:a2]:", false},
		{"every pair guard-refused", "Volgens artikel 7:13 BW [eu:a2][eu:a3]:", true},
	} {
		t.Run(c.name, func(t *testing.T) {
			res, err := VerifyAnswer(context.Background(), c.lead+item, evidence,
				VerifyOptions{AnswerLanguage: "nl", AdmitParaphrase: true, Checker: lowChecker{}, CheckerName: "low"})
			if err != nil {
				t.Fatal(err)
			}
			var got *string
			for i := range res.Claims {
				if strings.Contains(res.Claims[i].Claim, "schade") {
					got = &res.Claims[i].Reason
				}
			}
			if got == nil {
				t.Fatalf("no item claim: %+v", res.Claims)
			}
			isGuard := strings.Contains(*got, " guard")
			if strings.Contains(*got, "(model:") {
				isGuard = false
			}
			if isGuard != c.guard {
				t.Fatalf("reason %q; want a %s refusal", *got, map[bool]string{true: "guard", false: "model"}[c.guard])
			}
		})
	}
}
