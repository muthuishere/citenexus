// The verb guard: two distinct acts on the same object.
//
// "You take the additional leave four weeks in advance" over "De werknemer
// vraagt het aanvullend verlof … vier weken van tevoren aan" (rag_go triage
// L-R9): applying for leave and taking it are different acts, and the model
// reads them as one. A VerbPair is a closed class of two acts, each with its
// forms in any language; a Dutch separable form is written "vraagt+aan" (the
// verb, and its particle later in the same clause).
//
// The claim's clause binds one side; unit clauses that share an object word
// with it (a content word other than the verbs — in one language directly,
// across languages through VerifyOptions.Glossary) bind theirs. Refused when
// one such clause has the other act and the unit never states the claim's act
// at all. No shared object,
// or a claim clause with both acts, decides nothing; across languages without
// a glossary, no verdict. Hosts extend or replace the pairs with
// VerifyOptions.VerbPairs. Can only refuse.

package answer

import (
	"fmt"
	"strings"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

// VerbPair is two distinct acts, each with its forms in any language
// (lowercase; "verb+particle" for a Dutch separable verb).
type VerbPair struct {
	A, B []string
}

// DefaultVerbPairs: applying for something and taking or using it. The
// nominalisations count as the act: "(het) opnemen van", "opname van" (take),
// "aanvraag", "application" (apply).
var DefaultVerbPairs = []VerbPair{{
	A: []string{"aanvragen", "aanvraagt", "aangevraagd", "aanvraag", "aanvragen", "application", "vraagt+aan", "vraag+aan", "vragen+aan", "apply", "applies", "applied", "request", "requests", "requested"},
	B: []string{"opnemen", "opneemt", "opgenomen", "opname", "opnames", "neemt+op", "neem+op", "nemen+op", "take", "takes", "taken", "took", "use", "uses", "used"},
}}

// sideIn: 0 (A), 1 (B), -1 none or both, and the matched tokens' positions.
func sideIn(tokens []string, pair VerbPair) (int, map[int]bool) {
	hit := func(forms []string) map[int]bool {
		at := map[int]bool{}
		for _, f := range forms {
			verb, particle, separable := strings.Cut(f, "+")
			for i, t := range tokens {
				if t != verb {
					continue
				}
				if !separable {
					at[i] = true
					continue
				}
				for k := i + 1; k < len(tokens); k++ {
					if tokens[k] == particle {
						at[i], at[k] = true, true
						break
					}
				}
			}
		}
		return at
	}
	a, b := hit(pair.A), hit(pair.B)
	switch {
	case len(a) > 0 && len(b) == 0:
		return 0, a
	case len(b) > 0 && len(a) == 0:
		return 1, b
	}
	return -1, nil
}

// verbPairGuard: see the file comment.
func verbPairGuard(claim, claimLanguage string, eu EvidenceUnit, pairs []VerbPair, cfg guardConfig) string {
	cross := claimLanguage != "" && eu.Language != "" && primaryLanguage(claimLanguage) != primaryLanguage(eu.Language)
	if cross && len(cfg.glossary) == 0 {
		return ""
	}
	for _, pair := range pairs {
		for _, cc := range roleClauses(claim) {
			ct := tokenize.TokenizeV2(cc)
			side, verbAt := sideIn(ct, pair)
			if side < 0 {
				continue
			}
			c := carrier{claim: map[string]bool{}, crossLang: cross, translations: glossaryIndex(cfg.glossary)}
			for i, t := range ct {
				if !verbAt[i] {
					c.claim[t] = true
				}
			}
			agrees, other := false, ""
			for _, uc := range roleClauses(eu.Text) {
				ut := tokenize.TokenizeV2(uc)
				us, uAt := sideIn(ut, pair)
				if us < 0 {
					continue
				}
				// The claim's act anywhere in the unit leaves room for it: the
				// shared object is read through a partial glossary.
				if us == side {
					agrees = true
					continue
				}
				shared := false
				for i, t := range ut {
					if uAt[i] || gate.IsStopword(t) || isContextStop(t) || len([]rune(t)) < 4 {
						continue
					}
					if has, _ := c.carried(t); has {
						shared = true
						break
					}
				}
				if !shared {
					continue
				}
				if us == side {
					agrees = true
				} else if other == "" {
					for i := range ut {
						if uAt[i] {
							other = ut[i]
							break
						}
					}
				}
			}
			if !agrees && other != "" {
				claimVerb := ""
				for i := range ct {
					if verbAt[i] {
						claimVerb = ct[i]
						break
					}
				}
				return fmt.Sprintf("verb guard: the claim says %q where the passage says %q", claimVerb, other)
			}
		}
	}
	return ""
}
