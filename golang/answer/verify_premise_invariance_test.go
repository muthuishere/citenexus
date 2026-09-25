package answer

import (
	"context"
	"reflect"
	"regexp"
	"sync"
	"testing"
)

// recordingChecker scores every passage low and records what it was asked.
type recordingChecker struct {
	mu    sync.Mutex
	calls []string
}

func (r *recordingChecker) Check(_ context.Context, claim, passage string) (float64, float64, error) {
	r.mu.Lock()
	r.calls = append(r.calls, passage)
	r.mu.Unlock()
	if passage == premiseInvarianceHigh {
		return 0.75, 0.01, nil
	}
	return 0.018, 0.02, nil
}

const premiseInvarianceHigh = "Veiligheid. De directie beschermt een medewerker die een incident te goeder trouw en naar behoren meldt."

var bestOn = regexp.MustCompile(`best entailment ([0-9.]+), contradiction ([0-9.]+) on (\S+?)[;)]`)

// TestOptionsNeverMovePremiseSelection: the premises the host's checker is
// asked about, and the premise the result reports, are the same whatever an
// option does to a guard's verdict. rag_go measured ConjunctPresence moving
// an NLI score 0.018 -> 0.750 on a real claim: a unit a guard refused was
// never scored, so a guard verdict decided what the model saw.
func TestOptionsNeverMovePremiseSelection(t *testing.T) {
	gloss := [][2]string{{"directie", "management"}, {"beschermt", "protects"}, {"medewerker", "employee"},
		{"incident", "incident"}, {"goeder", "good"}, {"trouw", "faith"}, {"meldt", "reports"}}
	evidence := []EvidenceUnit{
		{ID: "a", DocumentID: "d", Language: "nl", Text: premiseInvarianceHigh},
		{ID: "b", DocumentID: "d", Language: "nl", Text: "Meldingen. Meldingen gaan naar de veiligheidskundige van de directie."},
	}
	for _, c := range []struct{ name, claim string }{
		// ConjunctPresence refuses unit a (a conjunct dropped); off, no guard fires.
		{"a guard verdict differs between the modes", "Management protects an employee who reports an incident in good faith [eu:a][eu:b]."},
		// No guard fires in either mode.
		{"no guard fires", "Management protects an employee who reports an incident in good faith and properly [eu:a][eu:b]."},
	} {
		t.Run(c.name, func(t *testing.T) {
			var calls [2][]string
			var reported [2]string
			for i, on := range []bool{false, true} {
				rec := &recordingChecker{}
				res, err := VerifyAnswer(context.Background(), c.claim, evidence, VerifyOptions{AnswerLanguage: "en",
					Glossary: gloss, ConjunctPresence: on, Checker: rec, CheckerName: "rec"})
				if err != nil {
					t.Fatal(err)
				}
				calls[i] = rec.calls
				if m := bestOn.FindStringSubmatch(res.Claims[0].Reason); m != nil {
					reported[i] = m[1] + "/" + m[2] + "/" + m[3]
				}
			}
			if !reflect.DeepEqual(calls[0], calls[1]) {
				t.Fatalf("the checker saw different premises:\n off: %q\n on:  %q", calls[0], calls[1])
			}
			if reported[0] != reported[1] {
				t.Fatalf("reported premise moved: off %q, on %q", reported[0], reported[1])
			}
		})
	}
}
