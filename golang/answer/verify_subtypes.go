// The subtype guard: the bare head noun for a fact the unit states only of a
// subtype.
//
// "Tijdens verlof ontvang je een uitkering" over "Tijdens het zwangerschaps-
// en bevallingsverlof ontvangt de werknemer een uitkering" (rag_go triage
// L-R23): the unit speaks only of one kind of leave; the claim makes it all
// leave. For a small class of head nouns whose subtypes are different facts
// (SubtypeHead: verlof/leave, toelage/allowance, vergoeding/reimbursement,
// uitkering/benefit — forms in any language, host-extensible through
// VerifyOptions.SubtypeHeads), a claim that uses the head BARE (no modifier
// before it, not inside a compound) over a unit where the head occurs only as
// the head of compounds ("bevallingsverlof", "zwangerschaps-") or behind a
// known scope qualifier ("onbetaald verlof"), and never otherwise, is refused.
//
// Limited on purpose to these heads: over-refusal is the risk, and a bare
// head in the unit anywhere gives no verdict. The class is language-free, so
// no glossary is needed. Can only refuse.

package answer

import (
	"fmt"
	"strings"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

// SubtypeHead is one head noun with its forms in any language (lowercase).
type SubtypeHead struct {
	Forms []string
}

// DefaultSubtypeHeads: leave, allowance, reimbursement, benefit.
var DefaultSubtypeHeads = []SubtypeHead{
	{Forms: []string{"verlof", "leave"}},
	{Forms: []string{"toelage", "toelagen", "allowance", "allowances"}},
	{Forms: []string{"vergoeding", "vergoedingen", "reimbursement", "reimbursements"}},
	{Forms: []string{"uitkering", "uitkeringen", "benefit", "benefits"}},
}

// bareUse: tokens[i] is a head form used without a modifier before it.
func bareUse(tokens []string, i int) bool {
	if i == 0 {
		return true
	}
	prev := tokens[i-1]
	if gate.IsStopword(prev) || isContextStop(prev) || isArticle(prev) {
		return true
	}
	// A measure is not a subtype: "twee dagen verlof", "12,5 ✓ uitkering".
	if _, isNum := numberValue(prev, ""); isNum {
		return true
	}
	if _, _, unit := unitOf(prev); unit {
		return true
	}
	if _, prep := groupPrepositions[prev]; prep {
		return true
	}
	switch prev {
	case "tijdens", "during", "bij", "voor", "for", "zonder", "without", "geen", "no":
		return true
	}
	return false
}

// subtypeGuard: see the file comment.
func subtypeGuard(claim string, eu EvidenceUnit, cfg guardConfig) string {
	claimTokens := tokenize.TokenizeV2(claim)
	unitTokens := tokenize.TokenizeV2(eu.Text)
	for _, head := range cfg.subtypes {
		claimBare := ""
		for i, t := range claimTokens {
			if hasTerm(head.Forms, t) && bareUse(claimTokens, i) {
				claimBare = t
			}
		}
		if claimBare == "" {
			continue
		}
		bare, qualified, example := false, false, ""
		for i, t := range unitTokens {
			if hasTerm(head.Forms, t) {
				// A separate modifier counts only when it is a known scope
				// qualifier ("onbetaald verlof", "additional leave"); any other
				// word before the head ("who need leave") says nothing.
				if i > 0 {
					if _, q := scopeQualifiers[unitTokens[i-1]]; q {
						qualified = true
						example = unitTokens[i-1] + " " + t
						continue
					}
				}
				bare = true
				continue
			}
			for _, f := range head.Forms {
				if len(t) > len(f)+2 && strings.HasSuffix(t, f) {
					qualified = true
					example = t
				}
			}
		}
		if qualified && !bare {
			return fmt.Sprintf("subtype guard: the claim says %q; the passage only speaks of %q", claimBare, example)
		}
	}
	return ""
}
