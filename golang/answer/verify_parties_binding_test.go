package answer

import (
	"context"
	"testing"
)

type admitAll struct{}

func (admitAll) Check(context.Context, string, string) (float64, float64, error) {
	return 0.999, 0, nil
}

// TestPartySwapBindsTheValueToItsWord: a unit that names both words of a pair
// (maximumprijs / minimumprijs, upper / lower limit, …) states each value for
// one of them. A claim stating a value with the word the unit binds it to is
// admitted; with the other word it is refused. rag_go spike 204: "De
// maximumprijs … is € 4.000" was refused as "role guard: maximumprijs where
// the passage says minimumprijs" because the claim aligned only after the
// swap, whatever word governed the value.
func TestPartySwapBindsTheValueToItsWord(t *testing.T) {
	oneSentenceNL := "Fietsregeling. De minimumprijs van een fiets is € 500 en de maximumprijs is € 4.000."
	oneSentenceEN := "Bike scheme. The minimum price of a bike is € 500 and the maximum price is € 4,000."
	twoSentencesNL := "Toeslag. De ondergrens van de toeslag is € 100. De bovengrens van de toeslag is € 300."
	twoSentencesEN := "Allowance. The lower limit of the allowance is € 100. The upper limit of the allowance is € 300."
	cases := []struct {
		name, lang, unit, claim string
		refuse                  bool
	}{
		{"nl right word, value after the other word", "nl", oneSentenceNL, "De maximumprijs van een fiets is € 4.000.", false},
		{"nl right word, own clause", "nl", oneSentenceNL, "De minimumprijs van een fiets is € 500.", false},
		{"nl wrong word for 4.000", "nl", oneSentenceNL, "De minimumprijs van een fiets is € 4.000.", true},
		{"nl wrong word for 500", "nl", oneSentenceNL, "De maximumprijs van een fiets is € 500.", true},
		{"en right word", "en", oneSentenceEN, "The maximum price of a bike is € 4,000.", false},
		{"en wrong word", "en", oneSentenceEN, "The minimum price of a bike is € 4,000.", true},
		{"nl two sentences, right word", "nl", twoSentencesNL, "De bovengrens van de toeslag is € 300.", false},
		{"nl two sentences, wrong word", "nl", twoSentencesNL, "De ondergrens van de toeslag is € 300.", true},
		{"en two sentences, right word", "en", twoSentencesEN, "The upper limit of the allowance is € 300.", false},
		{"en two sentences, wrong word", "en", twoSentencesEN, "The lower limit of the allowance is € 300.", true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			ev := []EvidenceUnit{{ID: "a", DocumentID: "d", Language: c.lang, Text: c.unit}}
			res, err := VerifyAnswer(context.Background(), c.claim+" [eu:a]", ev,
				VerifyOptions{AnswerLanguage: c.lang, AdmitParaphrase: true, Checker: admitAll{}, CheckerName: "admit"})
			if err != nil {
				t.Fatal(err)
			}
			if len(res.Claims) != 1 {
				t.Fatalf("%d claims", len(res.Claims))
			}
			got := res.Claims[0]
			if c.refuse && got.Supported {
				t.Fatalf("admitted; the unit binds the value to the other word")
			}
			if !c.refuse && !got.Supported {
				t.Fatalf("refused (%s); the unit binds the value to the claim's word", got.Reason)
			}
		})
	}
}
