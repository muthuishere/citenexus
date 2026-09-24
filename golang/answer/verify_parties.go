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
	"sort"
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
					if sameQuantityIn(q, theirs) {
						agrees = true
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

// ─── subject swap, through the glossary ─────────────────────────────────────

// SUBJECT SWAP. partySwapGuard needs the claim near-verbatim to the unit, so
// an English claim over a Dutch unit escapes it: "The team leader publishes
// the duty roster …" over "Het teamsecretariaat publiceert het dienstrooster
// …" (rag_go adv rx-v2-27), "the branch manager sets the holiday schedule"
// over "De planner stelt … de vakantieplanning vast" (rx-v2-39).
// subjectSwapGuard binds a claim's "party + verb" pair — the party a
// determiner-introduced noun of the unit, written in the claim as itself or as
// one of its VerifyOptions.Glossary translations, the verb the next word that
// is not a modal — to the unit sentences whose words include that verb (as
// itself or a translation). Each such sentence's subject is its opening
// determiner noun, or, with the verb first ("… beslist de vestigingsmanager"),
// the determiner noun right after the verb. A party is a noun that opens a
// unit sentence with its determiner, or follows a glossary-covered verb so. Refused when a
// sentence with the verb has another party as its subject and none has the
// claim's. ACROSS LANGUAGES ONLY, through the glossary for both the party and
// the verb — without a glossary, or in one language (partySwapGuard's), no
// verdict.
// Can only refuse.

var modalWords = map[string]struct{}{
	"must": {}, "may": {}, "can": {}, "will": {}, "shall": {}, "should": {}, "moet": {}, "mag": {}, "kan": {}, "zal": {}, "dient": {},
}

func subjectSwapGuard(claim, claimLanguage string, eu EvidenceUnit, cfg guardConfig) string {
	// Across languages, through the glossary, only: in one language the
	// near-verbatim party swap (partySwapGuard) is the sound check, and a
	// "noun + next word" pair read in the same language binds too loosely.
	cross := claimLanguage != "" && eu.Language != "" && primaryLanguage(claimLanguage) != primaryLanguage(eu.Language)
	if !cross || len(cfg.glossary) == 0 {
		return ""
	}
	gloss := glossaryIndex(cfg.glossary)
	forms := func(w string) [][]string { return gloss[w] }
	var sentences [][]string
	for _, s := range sentenceBreak.Split(softJoin(eu.Text), -1) {
		if toks := tokenize.TokenizeV2(s); len(toks) > 0 {
			sentences = append(sentences, toks)
		}
	}
	claimTokens := tokenize.TokenizeV2(claim)
	subjectOf := func(toks []string, verb int) []string {
		if len(toks) > 1 {
			// The verb right after the opening subject (Dutch V2: "De controller
			// sluit …"); a word further on is not bound to it.
			_, modal := modalWords[toks[2%len(toks)]]
			if _, det := partyDeterminers[toks[0]]; det && partyWord(toks[1]) && (verb == 2 || (verb == 3 && modal)) {
				return []string{toks[1]}
			}
		}
		// Verb-first with the subject after it is Dutch word order ("Bij te
		// veel aanvragen beslist de vestigingsmanager"); in English the noun
		// after a verb is its object.
		if primaryLanguage(eu.Language) == "nl" && verb+2 < len(toks) {
			if _, det := partyDeterminers[toks[verb+1]]; det && partyWord(toks[verb+2]) {
				return []string{toks[verb+2]}
			}
		}
		return nil
	}
	// The parties: nouns that are the SUBJECT of some unit sentence.
	subjects := map[string]bool{}
	for _, toks := range sentences {
		if len(toks) > 2 {
			if _, det := partyDeterminers[toks[0]]; det && partyWord(toks[1]) {
				subjects[toks[1]] = true // "De teamleider beslist …"
			}
		}
		for j := range toks {
			if subj := subjectOf(toks, j); subj != nil && j > 0 {
				if _, ok := gloss[toks[j]]; ok {
					subjects[subj[0]] = true
				}
			}
		}
	}
	var parties [][]string
	for p := range subjects {
		// With classes known (GlossaryEntries), only a party or a group is one.
		if len(cfg.classOf) > 0 && !isParty(p, cfg) && !actorTerm(p, cfg.actors) {
			continue
		}
		parties = append(parties, []string{p})
	}
	sort.Slice(parties, func(i, j int) bool { return parties[i][0] < parties[j][0] })
	// verbMatches: unit token t (at j in toks) is the claim's verb, directly
	// or as a separable verb whose particle comes later in the sentence ("De
	// controller sluit … af" = afsluiten = close).
	verbMatches := func(toks []string, j int, claimVerb string) bool {
		t := toks[j]
		if gate.IsStopword(t) || !partyWord(t) {
			return false
		}
		// A split separable form ("sluit", "keert") is that verb only with its
		// particle later in the sentence.
		if p := cfg.sepOf[t]; p != "" {
			found := false
			for k := j + 1; k < len(toks); k++ {
				if toks[k] == p {
					found = true
				}
			}
			if !found {
				return false
			}
		}
		for _, vf := range forms(t) {
			if len(vf) == 1 && vf[0] == claimVerb {
				return true
			}
		}
		for k := j + 1; k < len(toks); k++ {
			if _, particle := separableParticles[toks[k]]; !particle {
				continue
			}
			stem := strings.TrimSuffix(strings.TrimSuffix(t, "t"), "en")
			for key, trs := range gloss {
				if !strings.HasPrefix(key, toks[k]) || !strings.HasPrefix(key[len(toks[k]):], stem) || len(stem) < 3 {
					continue
				}
				for _, vf := range trs {
					if len(vf) == 1 && vf[0] == claimVerb {
						return true
					}
				}
			}
		}
		return false
	}
	verbAfter := func(from int) string {
		v := from
		for v < len(claimTokens) {
			if _, modal := modalWords[claimTokens[v]]; !modal {
				break
			}
			v++
		}
		if v >= len(claimTokens) {
			return ""
		}
		return claimTokens[v]
	}
	// check binds the claim party (a unit party, or the reader) to claimVerb.
	check := func(party string, reader bool, claimVerb string) string {
		agrees, other := false, ""
		for _, toks := range sentences {
			for j := range toks {
				if !verbMatches(toks, j, claimVerb) {
					continue
				}
				subj := subjectOf(toks, j)
				if subj == nil {
					continue
				}
				switch {
				case reader && actorTerm(subj[0], cfg.actors):
					// The reader may be that employee or that employer: no verdict.
					agrees = true
				case reader && !isParty(subj[0], cfg):
					// Not known to be a party at all ("de uitkering"): no verdict.
					agrees = true
				case !reader && (subj[0] == party || sameActorClass(subj[0], party, cfg.actors)):
					agrees = true
				case other == "":
					other = subj[0]
				}
			}
		}
		if !agrees && other != "" {
			return fmt.Sprintf("role guard: %q %s where the passage says %q does", party, claimVerb, other)
		}
		return ""
	}
	for _, p := range parties {
		for _, f := range forms(p[0]) {
			for _, sp := range findSpans(claimTokens, f) {
				if claimVerb := verbAfter(sp.end); claimVerb != "" {
					if reason := check(p[0], false, claimVerb); reason != "" {
						return reason
					}
				}
			}
		}
	}
	// The reader as the claim's subject ("You close …") against a THIRD party
	// — one the lexicon does not name, and that VerifyOptions.GlossaryEntries
	// class as a party or group: who "you" is (employee or employer) depends
	// on who asked, and "de uitkering" is no party at all.
	for i, t := range claimTokens {
		// Subject forms only: "your salary" is a possessive, not the actor.
		if _, subject := readerSubjects[t]; !subject {
			continue
		}
		if claimVerb := verbAfter(i + 1); claimVerb != "" {
			if reason := check(t, true, claimVerb); reason != "" {
				return reason
			}
		}
	}
	return ""
}

// separableParticles open a Dutch separable verb split around its object
// ("sluit … af", "vraagt … aan").
var separableParticles = map[string]struct{}{
	"af": {}, "aan": {}, "op": {}, "in": {}, "uit": {}, "mee": {}, "door": {}, "over": {},
	"terug": {}, "vast": {}, "toe": {}, "voor": {}, "bij": {}, "na": {},
}

func sameActorClass(a, b string, lexicon ActorLexicon) bool {
	for _, terms := range lexicon.Actors {
		if hasTerm(terms, a) && hasTerm(terms, b) {
			return true
		}
	}
	return false
}

// readerSubjects are the reader's pronouns in subject form.
var readerSubjects = map[string]struct{}{"you": {}, "je": {}, "jij": {}, "u": {}}

// isParty: the glossary classes the noun as a party or a group. Without
// classes nothing is known to be a third party.
func isParty(noun string, cfg guardConfig) bool {
	c := cfg.classOf[noun]
	return c == "party" || c == "group"
}
