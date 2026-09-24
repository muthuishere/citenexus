// Party swaps and value rows: two binding checks beyond the actor lexicon.
//
// PARTY SWAP. The role guard knows the parties its lexicon names. Policy text
// names others — "het bestuur", "de ondernemingsraad", "de planner", "de
// controller" — and rag_go's checker admits them swapped at P(E) 0.96–0.9995
// ("De ondernemingsraad legt … voor aan het bestuur" over "Het bestuur legt …
// voor aan de ondernemingsraad"). partySwapGuard needs no lexicon of parties:
// a party is any content word the unit introduces with a determiner ("de
// planner", "het college van bestuur"). The claim is refused when it does NOT
// align with any sentence of the unit as written, but DOES once one of its
// parties is replaced by another party of the unit, or two of its parties are
// exchanged. The reader's pronoun ("je", "u", "you") counts as a party of the
// claim: replacing it by a named THIRD party — one the lexicon does not name
// ("De controller sluit … af") — is a swap; by werkgever or werknemer it is
// not, because who "you" is depends on who asked.
// Articles are ignored on both sides ("een chauffeur" = "de chauffeur"), and
// parties the lexicon puts in one actor class (werknemer, medewerker) are one
// party.
//
// SOUND SAME-LANGUAGE ONLY: the alignment is the gate's token alignment, so the
// claim must be near-verbatim to the unit. An English claim over a Dutch unit
// ("The complaints committee decides …" over "Het college van bestuur beslist
// …") is left to the checker: aligning verbs across languages needs a
// glossary this library does not have. A claim that aligns as written is never
// refused here.
//
// VALUE ROW. A number stated for one period is moved to another: "During the
// first two years of illness, you receive 100%" over "Tijdens het eerste
// ziektejaar … 100% … In het tweede ziektejaar … 70%". valueRowGuard binds each
// claim number to the time quantities of its sentence (quantities(): "two years",
// "eerste ziektejaar" = 1 year, both languages) other than the number's own,
// finds the unit sentences holding the same number (ADR-0015 key), and
// refuses when those that state a period never state the claim's (a sentence
// holding the number without any period counts as agreeing).
//
// Both can only refuse.

package answer

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

var partyDeterminers = map[string]struct{}{
	"de": {}, "het": {}, "een": {}, "the": {}, "a": {}, "an": {},
	"zijn": {}, "haar": {}, "hun": {}, "his": {}, "her": {}, "their": {},
}

var articles = map[string]struct{}{"de": {}, "het": {}, "een": {}, "the": {}, "a": {}, "an": {}}

var sentenceBreak = regexp.MustCompile(`[.!?;]+(\s|$)|\n`)

func withoutArticles(tokens []string) []string {
	out := make([]string, 0, len(tokens))
	for _, t := range tokens {
		if _, ok := articles[t]; !ok {
			out = append(out, t)
		}
	}
	return out
}

func partyWord(t string) bool {
	if len([]rune(t)) < 3 || strings.ContainsAny(t, "0123456789") || gate.IsStopword(t) {
		return false
	}
	_, stop := contextStop[t]
	return !stop
}

// unitParties are the determiner-introduced noun phrases of the unit: one
// word, or "X van Y" ("college van bestuur").
func unitParties(sentences [][]string) [][]string {
	seen := map[string]bool{}
	var out [][]string
	for _, toks := range sentences {
		for i := 0; i+1 < len(toks); i++ {
			if _, det := partyDeterminers[toks[i]]; !det || !partyWord(toks[i+1]) {
				continue
			}
			phrases := [][]string{{toks[i+1]}}
			if i+3 < len(toks) && toks[i+2] == "van" && partyWord(toks[i+3]) {
				phrases = append(phrases, []string{toks[i+1], "van", toks[i+3]})
			}
			for _, p := range phrases {
				if k := strings.Join(p, " "); !seen[k] {
					seen[k] = true
					out = append(out, p)
				}
			}
		}
	}
	return out
}

type span struct{ start, end int } // [start, end)

func findSpans(tokens, phrase []string) []span {
	var out []span
	for i := 0; i+len(phrase) <= len(tokens); i++ {
		if equalTokens(tokens[i:i+len(phrase)], phrase) {
			out = append(out, span{i, i + len(phrase)})
		}
	}
	return out
}

func replaceSpans(tokens []string, repl map[span][]string) []string {
	out := []string{}
	for i := 0; i < len(tokens); {
		done := false
		for s, r := range repl {
			if s.start == i {
				out = append(out, r...)
				i = s.end
				done = true
				break
			}
		}
		if !done {
			out = append(out, tokens[i])
			i++
		}
	}
	return out
}

// partySwapGuard: see the file comment.
func partySwapGuard(claim, passage string, lexicon ActorLexicon) string {
	var sentences, bare [][]string
	for _, s := range sentenceBreak.Split(softJoin(passage), -1) {
		if toks := tokenize.TokenizeV2(s); len(toks) > 0 {
			sentences = append(sentences, toks)
			bare = append(bare, withoutArticles(toks))
		}
	}
	claimTokens := withoutArticles(tokenize.TokenizeV2(claim))
	if len(claimTokens) == 0 {
		return ""
	}
	aligns := func(tokens []string) bool {
		for _, s := range bare {
			if _, ok := gate.Align(tokens, s); ok {
				return true
			}
		}
		return false
	}
	if aligns(claimTokens) {
		return ""
	}
	parties := unitParties(sentences)
	classOf := func(p []string) string {
		if len(p) != 1 {
			return ""
		}
		for id, terms := range lexicon.Actors {
			for _, t := range terms {
				if t == p[0] {
					return id
				}
			}
		}
		return ""
	}
	type occurrence struct {
		at      span
		party   []string
		pronoun bool
	}
	var inClaim []occurrence
	for _, p := range parties {
		for _, s := range findSpans(claimTokens, p) {
			inClaim = append(inClaim, occurrence{at: s, party: p})
		}
	}
	for _, t := range lexicon.SecondPersonTerms {
		for _, s := range findSpans(claimTokens, []string{t}) {
			inClaim = append(inClaim, occurrence{at: s, party: []string{t}, pronoun: true})
		}
	}
	same := func(a, b []string, aPronoun bool) bool {
		if equalTokens(a, b) {
			return true
		}
		ca, cb := classOf(a), classOf(b)
		if aPronoun {
			ca = lexicon.SecondPerson
		}
		return ca != "" && ca == cb
	}
	// One party replaced by another party of the unit. The reader's pronoun
	// is replaced only by a THIRD party — one the lexicon does not name: who
	// "you" is (employee or employer) depends on who asked, so "U mag niet
	// vragen …" over "De werkgever mag niet vragen …" decides nothing, while
	// "Je sluit … af" over "De controller sluit … af" is a swap.
	for _, o := range inClaim {
		for _, p := range parties {
			if same(o.party, p, o.pronoun) || (o.pronoun && classOf(p) != "") {
				continue
			}
			if aligns(replaceSpans(claimTokens, map[span][]string{o.at: p})) {
				return fmt.Sprintf("role guard: %q where the passage says %q", strings.Join(o.party, " "), strings.Join(p, " "))
			}
		}
	}
	// Two parties of the claim exchanged.
	for i, a := range inClaim {
		for _, b := range inClaim[i+1:] {
			if a.at.end > b.at.start && b.at.end > a.at.start {
				continue
			}
			if same(a.party, b.party, a.pronoun) {
				continue
			}
			if aligns(replaceSpans(claimTokens, map[span][]string{a.at: b.party, b.at: a.party})) {
				return fmt.Sprintf("role guard: %q and %q are exchanged", strings.Join(a.party, " "), strings.Join(b.party, " "))
			}
		}
	}
	return ""
}

// valueRowGuard: see the file comment.
func valueRowGuard(claim, claimLanguage string, eu EvidenceUnit) string {
	periods := func(clause, language string, own string) map[[2]string]struct{} {
		out := map[[2]string]struct{}{}
		for q := range quantities(clause, language) {
			if q[0] != own {
				out[q] = struct{}{}
			}
		}
		return out
	}
	// Sentences, not clauses: a period is often a fronted adverbial set off by
	// a comma ("During the first year of illness, you receive 100%").
	_, unitText := clockTimes(eu.Text) // clock times are compared by the number guard
	_, claimText := clockTimes(claim)
	unitClauses := sentenceBreak.Split(softJoin(unitText), -1)
	for _, c := range sentenceBreak.Split(softJoin(claimText), -1) {
		for _, m := range numbersIn(c, claimLanguage) {
			key := m.reading.Key
			mine := periods(c, claimLanguage, key)
			if len(mine) == 0 {
				continue
			}
			matched, agrees, other := false, false, [2]string{}
			for _, uc := range unitClauses {
				has := false
				for _, um := range numbersIn(uc, eu.Language) {
					if um.reading.Key == key {
						has = true
						break
					}
				}
				if !has {
					continue
				}
				theirs := periods(uc, eu.Language, key)
				if len(theirs) == 0 {
					agrees = true // the unit states the value without a period here
					continue
				}
				matched = true
				for q := range mine {
					if _, ok := theirs[q]; ok {
						agrees = true
					}
					if eq, ok := equivalentQuantity(q); ok {
						if _, ok := theirs[eq]; ok {
							agrees = true
						}
					}
				}
				if other == ([2]string{}) {
					for q := range theirs {
						if other == ([2]string{}) || q[0] < other[0] {
							other = q
						}
					}
				}
			}
			if matched && !agrees {
				var claimed [2]string
				for q := range mine {
					if claimed == ([2]string{}) || q[0] < claimed[0] {
						claimed = q
					}
				}
				return fmt.Sprintf("value guard: %s for %s %s where the passage says %s %s",
					strings.TrimPrefix(key, "?"), claimed[0], claimed[1], other[0], other[1])
			}
		}
	}
	return ""
}
