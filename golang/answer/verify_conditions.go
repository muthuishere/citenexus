// The condition guard: a model-admitted claim that drops the unit's condition.
//
// The model admits a claim that states the rule without its condition or
// scope: "Werknemers ontvangen een eindejaarsuitkering" over "Werknemers met
// een vast dienstverband die ten minste twaalf maanden in dienst zijn,
// ontvangen …"; "Tijdens verlof …" over "Tijdens het onbetaald verlof …";
// "Bij ongewenst gedrag kun je terecht bij de vertrouwenspersoon" over "Kom je
// er met de betrokkene niet uit, dan kun je terecht …". The gate cannot admit
// always refuse these: its alignment may skip a qualifier inside a gap
// ("Tijdens verlof …" over "Tijdens het onbetaald verlof …"). So this guard
// runs on the model path (in guards()) and after every gate admission.
//
// It finds the unit sentence the claim follows (the most shared content
// words, at least two) and reads its restrictors:
//
//   - an opener and what follows it, up to the next word the claim shares or
//     the clause end: mits, indien, tenzij, (op) voorwaarde, alleen,
//     uitsluitend, enkel, slechts, eerst, pas, zolang, behalve, uitgezonderd,
//     "ten minste", "met toestemming" (not "niet alleen"); "die" and "met" right
//     after a party the actor lexicon names ("Werknemers met een vast
//     dienstverband", "Advocaat-stagiaires die in het eerste jaar …") — and
//     their English counterparts;
//   - a conditional sentence opened by its verb ("Kom je … niet uit, dan …"):
//     everything before "dan";
//   - a scope qualifier right before a word the claim shares ("onbetaald
//     verlof", "vaste en variabele toeslagen");
//   - a coordinated requirement dropped from inside the claim's span ("te
//     goeder trouw en zorgvuldig melden" where the claim keeps both ends).
//
// A restrictor whose content words the claim lacks — all of them for a
// qualifier or a coordinated word, at least half for an opener's segment —
// refuses the claim. Can only refuse.
//
// SAME LANGUAGE, OR THROUGH THE CALLER'S GLOSSARY. "The claim lacks the word"
// is only testable in the unit's language. For a claim in another language the
// guard needs VerifyOptions.Glossary: a unit word counts as carried when the
// claim holds it or every word of one of its translations; a restrictor with a
// word the glossary does not cover gives no verdict, and without a glossary no
// cross-language claim is judged. That is what can be made sound here: a
// glossary miss must never turn into a refusal, and never into an admission.

package answer

import (
	"fmt"
	"strings"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

var conditionOpeners = map[string]struct{}{
	"mits": {}, "indien": {}, "tenzij": {}, "voorwaarde": {}, "alleen": {}, "uitsluitend": {},
	"enkel": {}, "slechts": {}, "eerst": {}, "pas": {}, "zolang": {}, "behalve": {}, "uitgezonderd": {},
	"provided": {}, "unless": {}, "only": {}, "solely": {}, "first": {}, "except": {}, "once": {},
}

// conditionPhrases are two-word openers.
var conditionPhrases = [][2]string{
	{"ten", "minste"}, {"met", "toestemming"}, {"at", "least"}, {"with", "permission"},
}

// partyRestrictors open a restriction only right after a party: "Werknemers
// met …", "Advocaat-stagiaires die …".
var partyRestrictors = map[string]struct{}{"met": {}, "die": {}, "with": {}, "who": {}}

var scopeQualifiers = map[string]struct{}{
	"onbetaald": {}, "onbetaalde": {}, "betaald": {}, "betaalde": {}, "aanvullend": {}, "aanvullende": {},
	"bijzonder": {}, "bijzondere": {}, "vast": {}, "vaste": {}, "tijdelijk": {}, "tijdelijke": {},
	"variabel": {}, "variabele": {}, "gewoon": {}, "gewone": {},
	"unpaid": {}, "paid": {}, "additional": {}, "special": {}, "fixed": {}, "variable": {},
	"regular": {}, "temporary": {}, "permanent": {},
}

var conditionalVerbSubjects = map[string]struct{}{"je": {}, "jij": {}, "u": {}, "de": {}, "het": {}}

func conditionContent(t string) bool {
	if gate.IsStopword(t) {
		return false
	}
	if _, stop := contextStop[t]; stop {
		return false
	}
	// Short words ("wil", "zijn") are verbs and particles more than they are
	// conditions; digits always count.
	return len([]rune(t)) >= 4 || strings.ContainsAny(t, "0123456789")
}

// carried reports whether the claim carries unit word w: directly, or (other
// language) through a glossary translation. known is false when w has no
// glossary entry and the claim is in another language.
type carrier struct {
	claim        map[string]bool
	crossLang    bool
	translations map[string][][]string
}

func (c carrier) carried(w string) (has, known bool) {
	if c.claim[w] {
		return true, true
	}
	// An inflection or a plural ("bereikbaarheidsdienst" / "…diensten"): one
	// word is the other plus a short ending.
	if r := []rune(w); len(r) >= 6 {
		for t := range c.claim {
			if tr := []rune(t); len(tr) >= 6 && (strings.HasPrefix(t, w) || strings.HasPrefix(w, t)) &&
				abs(len(tr)-len(r)) <= 3 {
				return true, true
			}
		}
	}
	if !c.crossLang {
		return false, true
	}
	trs, ok := c.translations[w]
	if !ok {
		if strings.ContainsAny(w, "0123456789") {
			return false, true // a number reads the same in both languages
		}
		return false, false
	}
	for _, tr := range trs {
		all := true
		for _, t := range tr {
			if !c.claim[t] {
				all = false
				break
			}
		}
		if all {
			return true, true
		}
	}
	return false, true
}

func glossaryIndex(glossary [][2]string) map[string][][]string {
	out := map[string][][]string{}
	for _, pair := range glossary {
		for k := 0; k < 2; k++ {
			from, to := tokenize.TokenizeV2(pair[k]), tokenize.TokenizeV2(pair[1-k])
			if len(from) == 1 && len(to) > 0 {
				out[from[0]] = append(out[from[0]], to)
			}
		}
	}
	return out
}

// conditionGuard: see the file comment.
func conditionGuard(claim, claimLanguage string, eu EvidenceUnit, cfg guardConfig) string {
	cross := claimLanguage != "" && eu.Language != "" && primaryLanguage(claimLanguage) != primaryLanguage(eu.Language)
	if cross && len(cfg.glossary) == 0 {
		return ""
	}
	// Dates and clock times are compared as one token each ("01-06-2026" and
	// "1 juni 2026" are the same condition word).
	claim = canonicalDates(claim, claimLanguage)
	eu.Text = canonicalDates(eu.Text, eu.Language)
	c := carrier{claim: map[string]bool{}, crossLang: cross, translations: glossaryIndex(cfg.glossary)}
	claimTokens := tokenize.TokenizeV2(claim)
	for _, t := range claimTokens {
		c.claim[t] = true
	}
	claimBounds := boundDirections(claimTokens)
	shared := func(t string) bool {
		has, _ := c.carried(t)
		return conditionContent(t) && has
	}
	// The unit sentence(s) the claim follows: the most shared content words,
	// every sentence tied for it (a heading "Ongewenst gedrag." ties with the
	// sentence that restricts it; both are read).
	var ties []string
	previous := map[string]string{} // sentence -> the sentence before it
	bestN := 0
	claimHedges := hedgesIn(claimTokens, claim)
	prev := ""
	for _, s := range sentenceBreak.Split(softJoin(eu.Text), -1) {
		previous[s] = prev
		prev = s
		n := 0
		seen := map[string]bool{}
		for _, t := range tokenize.TokenizeV2(s) {
			// Any non-stopword counts for finding the sentence ("mag" too); only
			// the restrictor test needs content words of 4+ letters. Across
			// languages a role the claim names explicitly (werknemers =
			// employees, not the reader's "you") and a hedge of the same class
			// (mogen = may) count too.
			has, _ := c.carried(t)
			if !has && cross {
				if actorTerm(t, cfg.actors) && claimNamesRole(c.claim, t, cfg.actors) {
					has = true
				}
				for class := range hedgesIn([]string{t}, t) {
					if _, ok := claimHedges[class]; ok {
						has = true
					}
				}
			}
			if !seen[t] && has && !gate.IsStopword(t) && !isContextStop(t) {
				seen[t] = true
				n++
			}
		}
		switch {
		case n > bestN:
			ties, bestN = []string{s}, n
		case n == bestN && n > 0:
			ties = append(ties, s)
		}
	}
	if bestN < 2 {
		return ""
	}
	// lacks: the claim drops the restrictor. Same language: all its content
	// words missing (a qualifier, a coordinated word) or at least half (an
	// opener's segment). Across languages only glossary-covered words are
	// judged: every covered word must be missing, and the covered words must
	// be at least half of the segment — otherwise no verdict.
	lacks := func(words []string, half bool) (bool, string) {
		content, known, missing := 0, 0, 0
		first := ""
		for _, w := range words {
			if !conditionContent(w) {
				continue
			}
			content++
			has, ok := c.carried(w)
			if !ok {
				continue
			}
			known++
			if !has {
				missing++
				if first == "" {
					first = w
				}
			}
		}
		if content == 0 || known == 0 {
			return false, ""
		}
		if c.crossLang {
			return missing == known && 2*known >= content, first
		}
		if half {
			return 2*missing >= content && missing > 0, first
		}
		return missing == content, first
	}
	refuse := func(kind, word string) string {
		return fmt.Sprintf("condition guard: the passage restricts it (%s %q) and the claim drops it", kind, word)
	}

	for _, bestText := range ties {
		best := tokenize.TokenizeV2(bestText)
		// A consequent sentence ("Dan kun je …", "In dat geval …") holds only
		// under the sentence before it: that sentence is its condition.
		if len(best) > 1 && (best[0] == "dan" || best[0] == "then" ||
			(len(best) > 2 && best[0] == "in" && best[1] == "dat" && best[2] == "geval") ||
			(len(best) > 2 && best[0] == "in" && best[1] == "that" && best[2] == "case")) {
			if cond := previous[bestText]; cond != "" {
				if ok, w := lacks(tokenize.TokenizeV2(cond), true); ok {
					return refuse("condition", w)
				}
			}
		}
		// A conditional sentence opened by its verb: "Kom je … niet uit, dan …".
		if len(best) > 2 {
			if _, subj := conditionalVerbSubjects[best[1]]; subj && !gate.IsStopword(best[0]) && !isContextStop(best[0]) {
				for i, t := range best {
					if t == "dan" && i > 2 && strings.Contains(bestText, ", dan") {
						if ok, w := lacks(best[:i], false); ok {
							return refuse("condition", w)
						}
						break
					}
				}
			}
		}
		for _, clause := range clauseBreak.Split(softJoin(bestText), -1) {
			toks := tokenize.TokenizeV2(clause)
			// A restriction of a group the claim does not speak about ("Werknemers
			// die structureel ten minste twee dagen … thuiswerken, ontvangen …"
			// under "De thuiswerkvergoeding is € 2,40") is out of the claim's
			// scope, and so is every opener inside it.
			// Only a group in SUBJECT position (the clause's first noun) is out of
			// scope: "… vergoedt een bureaustoel voor werknemers met een vast
			// contract" restricts the predicate the claim states, so it stays.
			outOfScope := make([]bool, len(toks))
			for i := 1; i < len(toks); i++ {
				subject := i-1 == 0 || (i-1 == 1 && isArticle(toks[0]))
				if _, ok := partyRestrictors[toks[i]]; ok && subject && actorTerm(toks[i-1], cfg.actors) &&
					!claimNamesActor(c.claim, toks[i-1], cfg.actors) {
					for k := i; k < len(toks); k++ {
						outOfScope[k] = true
					}
					break
				}
			}
			for i := 0; i < len(toks); i++ {
				if outOfScope[i] {
					continue
				}
				start := -1
				negated := i > 0 && (toks[i-1] == "niet" || toks[i-1] == "not") // "niet alleen … maar ook"
				if _, ok := conditionOpeners[toks[i]]; ok && !negated {
					start = i + 1
					// An exclusion the claim restates itself ("… en geen
					// lease-auto heeft") is the exclusion guard's to judge.
					if _, excl := exclusionOpeners[toks[i]]; excl && boundOrNegation(claimTokens) {
						start = -1
					}
				}
				for _, ph := range conditionPhrases {
					if i+1 < len(toks) && toks[i] == ph[0] && toks[i+1] == ph[1] {
						start = i + 1 // "toestemming", "minste" belong to the condition
						// A bound the claim states its own way ("minimaal" for
						// "ten minste") is carried: the bound check is the negation
						// guard's and the number guard's.
						if claimBounds[boundLower] && (ph[1] == "minste" || ph[1] == "least") {
							start = -1
						}
					}
				}
				// "Werknemers met …" / "… die …": a restricted group (a subject
				// group the claim does not speak about was scoped out above).
				if _, ok := partyRestrictors[toks[i]]; ok && i > 0 && actorTerm(toks[i-1], cfg.actors) {
					start = i + 1
				}
				if start < 0 || start >= len(toks) {
					continue
				}
				end := start
				for end < len(toks) && !shared(toks[end]) {
					end++
				}
				if _, alreadyOpener := conditionOpeners[toks[i]]; !alreadyOpener && end == start {
					continue
				}
				if ok, w := lacks(toks[start:end], true); ok {
					return refuse("condition", toks[i]+" … "+w)
				}
			}
			// Scope qualifiers right before a shared word; "vaste en variabele
			// toeslagen" qualifies through the coordination.
			for i := 0; i+1 < len(toks); i++ {
				if _, q := scopeQualifiers[toks[i]]; !q {
					continue
				}
				j := i + 1
				for j+1 < len(toks) && (toks[j] == "en" || toks[j] == "and") {
					j += 2
				}
				if j < len(toks) && shared(toks[j]) {
					if ok, w := lacks([]string{toks[i]}, false); ok {
						return refuse("qualifier", w)
					}
				}
			}
			// A coordinated requirement dropped from inside the claim's span:
			// shared, "en", missing, shared.
			for i := 0; i+3 < len(toks); i++ {
				if shared(toks[i]) && (toks[i+1] == "en" || toks[i+1] == "and") && conditionContent(toks[i+2]) &&
					shared(toks[i+3]) {
					if ok, w := lacks([]string{toks[i+2]}, false); ok {
						return refuse("requirement", w)
					}
				}
			}
		}
	}
	return ""
}

func actorTerm(t string, lexicon ActorLexicon) bool {
	for _, terms := range lexicon.Actors {
		for _, x := range terms {
			if x == t {
				return true
			}
		}
	}
	return false
}

// claimNamesActor: the claim names the same actor as unit term t (any term of
// its class, in any language).
func claimNamesActor(claim map[string]bool, t string, lexicon ActorLexicon) bool {
	for id, terms := range lexicon.Actors {
		// The reader's pronoun names the SecondPerson actor.
		if id == lexicon.SecondPerson {
			for _, x := range lexicon.SecondPersonTerms {
				if claim[x] && hasTerm(terms, t) {
					return true
				}
			}
		}
		in := false
		for _, x := range terms {
			if x == t {
				in = true
				break
			}
		}
		if !in {
			continue
		}
		for _, x := range terms {
			if claim[x] {
				return true
			}
		}
	}
	return false
}

func hasTerm(terms []string, t string) bool {
	for _, x := range terms {
		if x == t {
			return true
		}
	}
	return false
}

func abs(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

func isContextStop(t string) bool {
	_, ok := contextStop[t]
	return ok
}

// canonicalDates replaces each date with one token, "d0106" (+ " y2026"), so
// a date matches however it is written.
func canonicalDates(text, language string) string {
	dates, _ := datesIn(text, language)
	if len(dates) == 0 {
		return text
	}
	lowered := strings.ToLower(text)
	var b strings.Builder
	last := 0
	for _, sp := range dateSpans(lowered, language) {
		b.WriteString(lowered[last:sp.start])
		d := sp.key
		if d.ambiguous != "" {
			b.WriteString(" " + d.ambiguous + " ")
		} else {
			fmt.Fprintf(&b, " d%02d%02d ", d.day, d.month)
			if d.year != 0 {
				fmt.Fprintf(&b, "y%d ", d.year)
			}
		}
		last = sp.end
	}
	b.WriteString(lowered[last:])
	return b.String()
}

var exclusionOpeners = map[string]struct{}{"behalve": {}, "uitgezonderd": {}, "except": {}}

// claimNamesRole: the claim names t's actor class by an explicit role term,
// not by the reader's pronoun.
func claimNamesRole(claim map[string]bool, t string, lexicon ActorLexicon) bool {
	for _, terms := range lexicon.Actors {
		if !hasTerm(terms, t) {
			continue
		}
		for _, x := range terms {
			if claim[x] {
				return true
			}
		}
	}
	return false
}
