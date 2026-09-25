// The exclusion guard: a claim that asserts a fact for a group the unit
// EXCLUDES from it.
//
// Dropping an exclusion is the condition guard's family: "Teachers who work
// from home … receive €2.35 per day" over "… ontvangen een vergoeding van
// € 2,35 per thuiswerkdag. Voor leraren en onderwijsondersteunend personeel
// geldt deze vergoeding niet." (rag_go adv gw-v2-15).
//
// A unit sentence excludes a group G when it says so with a marker —
// behalve, met uitzondering van, uitgezonderd, niet voor, niet van toepassing
// op, except, excluding, other than, with the exception of, not applicable
// to, not for — followed by G; or when a sentence opened by "voor G" / "for G"
// is negated ("Voor leraren … geldt deze vergoeding niet"); or when G is the
// subject of "is/zijn uitgesloten", "hebben geen recht", "komen niet in
// aanmerking", "are excluded", "are not entitled/eligible/enrolled". A list
// ("leraren en onderwijsondersteunend personeel") is several groups.
//
// The claim is refused when it names an excluded group — every content word
// of one group — or speaks about everyone ("alle", "iedereen", "all",
// "every"), unless it restates the exclusion itself (it carries an exclusion
// marker, a negation, "without"/"zonder"). A group word is read through the
// actor lexicon's language-free ids (stagiair = intern), in the unit's
// language, or through VerifyOptions.Glossary; a word none of them reads is
// skipped, and a group with no readable word gives NO VERDICT — end to end the
// checker is then the only barrier (gw-v2-15 without a glossary, "leraren"
// being no lexicon role). A claim about everyone over any exclusion is refused
// in any language. Can only refuse.

package answer

import (
	"fmt"
	"strings"

	"github.com/muthuishere/citenexus/golang/tokenize"
)

var exclusionMarkers = [][]string{
	{"behalve"}, {"uitgezonderd"}, {"met", "uitzondering", "van"}, {"niet", "voor"},
	{"niet", "van", "toepassing", "op"}, {"except"}, {"excluding"}, {"other", "than"},
	{"with", "the", "exception", "of"}, {"not", "applicable", "to"}, {"not", "for"},
}

// excludedPredicates follow an excluded group as its predicate.
var excludedPredicates = [][]string{
	{"zijn", "uitgesloten"}, {"is", "uitgesloten"}, {"hebben", "geen", "recht"}, {"heeft", "geen", "recht"},
	{"komen", "niet", "in", "aanmerking"}, {"komt", "niet", "in", "aanmerking"},
	{"are", "excluded"}, {"is", "excluded"}, {"are", "not", "entitled"}, {"is", "not", "entitled"},
	{"are", "not", "eligible"}, {"is", "not", "eligible"}, {"are", "not", "enrolled"}, {"is", "not", "enrolled"},
}

var universalWords = map[string]struct{}{
	"alle": {}, "iedereen": {}, "iedere": {}, "elke": {}, "ieder": {}, "all": {}, "every": {}, "everyone": {}, "everybody": {},
}

var groupVerbs = map[string]struct{}{
	"geldt": {}, "gelden": {}, "is": {}, "zijn": {}, "heeft": {}, "hebben": {}, "komt": {}, "komen": {},
	"krijgt": {}, "krijgen": {}, "ontvangt": {}, "ontvangen": {}, "kan": {}, "kunnen": {}, "mag": {}, "mogen": {},
	"applies": {}, "apply": {}, "are": {}, "has": {}, "have": {}, "can": {}, "may": {}, "receive": {}, "receives": {},
}

// splitGroups: a segment's groups, split at "en"/"and"/"or"/"of", each as its
// content words.
func splitGroups(tokens []string) [][]string {
	var out [][]string
	cur := []string{}
	flush := func() {
		if len(cur) > 0 {
			out = append(out, cur)
		}
		cur = []string{}
	}
	for _, t := range tokens {
		switch t {
		case "en", "and", "or", "of":
			flush()
			continue
		case "die", "dat", "who", "that", "which", "waarvan":
			// A relative clause describes the group; it is not another one
			// ("opleidingen die de werkgever verplicht stelt").
			flush()
			return out
		}
		if _, prep := groupPrepositions[t]; prep && len(cur) > 0 && !hasTerm(cur, qualifierMark) {
			cur = append(cur, qualifierMark) // "medewerkers | proeftijd …"
			continue
		}
		if conditionContent(t) {
			cur = append(cur, t)
		}
	}
	flush()
	return out
}

// qualifierMark separates a group's head ("medewerkers") from its
// prepositional qualifier ("in de proeftijd van een nieuw contract").
const qualifierMark = "|"

var groupPrepositions = map[string]struct{}{
	"in": {}, "met": {}, "van": {}, "vanaf": {}, "op": {}, "bij": {}, "with": {}, "from": {}, "of": {}, "on": {}, "at": {},
}

// excludedGroups reads the groups a unit sentence excludes.
func excludedGroups(tokens []string) [][]string {
	var groups [][]string
	// Marker + group, up to a verb or the end of the sentence.
	for i := range tokens {
		for _, m := range exclusionMarkers {
			if i+len(m) > len(tokens) || !equalTokens(tokens[i:i+len(m)], m) {
				continue
			}
			j := i + len(m)
			k := j
			for k < len(tokens) {
				if _, verb := groupVerbs[tokens[k]]; verb {
					break
				}
				k++
			}
			groups = append(groups, splitGroups(tokens[j:k])...)
		}
	}
	markers := 0
	for _, t := range tokens {
		if t == "niet" || t == "not" || t == "geen" || t == "no" {
			markers++
		}
	}
	// "Voor G … niet": a negated sentence opened by voor/for.
	if len(tokens) > 1 && (tokens[0] == "voor" || tokens[0] == "for") && markers > 0 {
		k := 1
		for k < len(tokens) {
			if _, verb := groupVerbs[tokens[k]]; verb {
				break
			}
			k++
		}
		groups = append(groups, splitGroups(tokens[1:k])...)
	}
	// "G zijn uitgesloten" / "G are not entitled": the subject before the
	// predicate.
	for i := range tokens {
		for _, p := range excludedPredicates {
			if i+len(p) <= len(tokens) && equalTokens(tokens[i:i+len(p)], p) {
				groups = append(groups, splitGroups(tokens[:i])...)
			}
		}
	}
	return groups
}

// exclusionGuard: see the file comment.
func exclusionGuard(claim, claimLanguage string, eu EvidenceUnit, cfg guardConfig) string {
	cross := claimLanguage != "" && eu.Language != "" && primaryLanguage(claimLanguage) != primaryLanguage(eu.Language)
	claimTokens := tokenize.TokenizeV2(claim)
	c := carrier{claim: map[string]bool{}, crossLang: cross, translations: cfg.gloss.idx()}
	for _, t := range claimTokens {
		c.claim[t] = true
	}
	// A claim that restates an exclusion ("except …", "zonder …", "geen …")
	// or is negated states no inclusion.
	if len(excludedGroups(claimTokens)) > 0 || boundOrNegation(claimTokens) {
		return ""
	}
	universal := false
	for i, t := range claimTokens {
		if _, ok := universalWords[t]; !ok {
			continue
		}
		// "once every four years", "elke week": a frequency, not everyone.
		if i+1 < len(claimTokens) {
			next := claimTokens[i+1]
			if _, isNum := numberValue(next, claimLanguage); isNum {
				continue
			}
			if _, _, unit := unitOf(next); unit {
				continue
			}
		}
		universal = true
	}
	// A group word is matched through the actor lexicon (language-free ids),
	// else in the unit's language or through the glossary; a word neither can
	// read is skipped, and a group with no readable word decides nothing.
	carried := func(w string) (has, known bool) {
		for _, terms := range cfg.actors.Actors {
			if hasTerm(terms, w) {
				for _, x := range terms {
					if c.claim[x] {
						return true, true
					}
				}
				return false, true
			}
		}
		return c.carried(w)
	}
	for _, s := range sentenceBreak.Split(softJoin(eu.Text), -1) {
		for _, g := range excludedGroups(tokenize.TokenizeV2(s)) {
			if universal {
				return fmt.Sprintf("exclusion guard: the claim speaks about everyone; the passage excludes %q", strings.Join(withoutMark(g), " "))
			}
			// The head may skip words no reader covers ("temporary agency
			// workers"); a qualifier decides WHICH members are excluded, so it
			// must be readable, and every readable word must be carried.
			all, known, qualifier, qualifierKnown := true, 0, false, 0
			qualifierWords, qualifierNumber := 0, false
			// A head naming a lexicon role is that role: its other words are
			// the role's name ("temporary agency workers" = uitzendkrachten).
			headRole := false
			for _, w := range g {
				if w == qualifierMark {
					break
				}
				if actorTerm(w, cfg.actors) {
					headRole = true
				}
			}
			for _, w := range g {
				if w != qualifierMark && !qualifier && headRole && !actorTerm(w, cfg.actors) {
					continue
				}
				if w == qualifierMark {
					qualifier = true
					continue
				}
				if qualifier {
					qualifierWords++
					if strings.ContainsAny(w, "0123456789") {
						qualifierNumber = true
					}
				}
				has, ok := carried(w)
				if !ok {
					continue
				}
				known++
				if qualifier {
					qualifierKnown++
				}
				if !has {
					all = false
				}
			}
			// Every qualifier word must be readable ("binnenlands vervoer" with
			// only "vervoer" in the glossary would match "international
			// transport"), unless a number pins it ("vanaf schaal 10").
			if qualifier && (qualifierKnown == 0 || (qualifierKnown < qualifierWords && !qualifierNumber)) {
				continue
			}
			if known > 0 && all {
				return fmt.Sprintf("exclusion guard: the passage excludes %q", strings.Join(withoutMark(g), " "))
			}
		}
	}
	return ""
}

func boundOrNegation(tokens []string) bool {
	for _, t := range tokens {
		switch t {
		case "niet", "not", "geen", "no", "never", "nooit", "without", "zonder", "behalve", "except", "excluding":
			return true
		}
	}
	return false
}

func withoutMark(g []string) []string {
	out := make([]string, 0, len(g))
	for _, w := range g {
		if w != qualifierMark {
			out = append(out, w)
		}
	}
	return out
}
