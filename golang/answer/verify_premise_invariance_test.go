package answer

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"regexp"
	"sort"
	"strings"
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
		for _, eager := range []bool{true, false} {
			t.Run(fmt.Sprintf("%s/eager=%v", c.name, eager), func(t *testing.T) {
				var calls [2][]string
				var reported [2]string
				var supported [2]bool
				for i, on := range []bool{false, true} {
					rec := &recordingChecker{}
					res, err := VerifyAnswer(context.Background(), c.claim, evidence, VerifyOptions{AnswerLanguage: "en",
						Glossary: gloss, ConjunctPresence: on, Checker: rec, CheckerName: "rec", eagerScoring: eager})
					if err != nil {
						t.Fatal(err)
					}
					calls[i], supported[i] = rec.calls, res.Claims[0].Supported
					if m := bestOn.FindStringSubmatch(res.Claims[0].Reason); m != nil {
						reported[i] = m[1] + "/" + m[2] + "/" + m[3]
					}
				}
				if reported[0] != reported[1] {
					t.Fatalf("reported premise moved: off %q, on %q", reported[0], reported[1])
				}
				// Eager: the very same calls. Lazy scores a guard-refused unit
				// only when its score can reach the output — later, so in
				// another order — and never when the claim is admitted; with
				// the verdict unchanged it is asked about the same premises.
				if !eager {
					if supported[0] != supported[1] {
						return
					}
					sort.Strings(calls[0])
					sort.Strings(calls[1])
				}
				if !reflect.DeepEqual(calls[0], calls[1]) {
					t.Fatalf("the checker saw different premises:\n off: %q\n on:  %q", calls[0], calls[1])
				}
			})
		}
	}
}

// TestLazyScoringMatchesEager: lazy scoring (the default) returns, for every
// pinned vector, byte-for-byte the Result eager scoring (61ceddf) returns —
// the same premise and scores reported — with fewer checker calls.
func TestLazyScoringMatchesEager(t *testing.T) {
	var file struct {
		Cases []verifyVector `json:"cases"`
	}
	raw, err := os.ReadFile("testdata/verify_answer.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(raw, &file); err != nil {
		t.Fatal(err)
	}
	var eagerCalls, lazyCalls, withChecker int
	for _, c := range file.Cases {
		if len(c.Checker) == 0 && len(c.CheckerClaims) == 0 {
			continue // no checker: nothing is scored
		}
		withChecker++
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
		run := func(eager bool) (string, int) {
			ck := &countingChecker{inner: idChecker{byPassage: map[string][2]float64{}, byClaim: map[[2]string][2]float64{}}}
			for key, s := range c.Checker {
				ck.inner.byPassage[premise(key)] = [2]float64{s[0], s[1]}
			}
			for key, claims := range c.CheckerClaims {
				for claim, s := range claims {
					ck.inner.byClaim[[2]string{claim, premise(key)}] = [2]float64{s[0], s[1]}
				}
			}
			opts := VerifyOptions{AnswerLanguage: c.AnswerLanguage, AdmitParaphrase: c.AdmitParaphrase, NameAliases: c.NameAliases,
				LeadInFrames: c.LeadInFrames, Glossary: c.Glossary, ConjunctPresence: c.ConjunctPresence,
				Checker: ck, CheckerName: "fake", eagerScoring: eager}
			for _, e := range c.GlossaryEntries {
				opts.GlossaryEntries = append(opts.GlossaryEntries, GlossaryEntry{NL: e.NL, EN: e.EN, LemmaNL: e.LemmaNL, LemmaEN: e.LemmaEN, Sep: e.Sep, Class: e.Class})
			}
			if len(c.Actors) > 0 {
				lexicon := DefaultActorLexicon
				for id, terms := range c.Actors {
					lexicon = lexicon.With(id, terms...)
				}
				opts.Actors = &lexicon
			}
			res, err := VerifyAnswer(context.Background(), c.Answer, evidence, opts)
			if err != nil {
				t.Fatalf("%s: %v", c.Name, err)
			}
			j, _ := json.Marshal(res)
			return string(j), ck.n
		}
		e, en := run(true)
		l, ln := run(false)
		if e != l {
			t.Errorf("%s: lazy output differs from eager\n eager: %s\n lazy:  %s", c.Name, e, l)
		}
		eagerCalls += en
		lazyCalls += ln
	}
	t.Logf("%d vectors with a checker: eager %d checker calls, lazy %d (%.1f%% fewer)",
		withChecker, eagerCalls, lazyCalls, 100*float64(eagerCalls-lazyCalls)/float64(eagerCalls))
	if lazyCalls > eagerCalls {
		t.Fatalf("lazy made more checker calls (%d) than eager (%d)", lazyCalls, eagerCalls)
	}
}

type countingChecker struct {
	inner idChecker
	n     int
}

func (c *countingChecker) Check(ctx context.Context, claim, passage string) (float64, float64, error) {
	c.n++
	return c.inner.Check(ctx, claim, passage)
}
