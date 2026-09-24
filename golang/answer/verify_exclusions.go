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
// marker or a negation). Same language directly; across languages only
// through VerifyOptions.Glossary, and a group word the glossary does not cover
// gives no verdict. With no glossary no cross-language claim is judged: the
// guard returns no verdict, and END TO END THE CHECKER IS THEN THE ONLY
// BARRIER for such a claim (gw-v2-15 is admitted by a checker that admits
// it). Pass the host's glossary to close it deterministically. Can only refuse.

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
		}
		if conditionContent(t) {
			cur = append(cur, t)
		}
	}
	flush()
	return out
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
	if cross && len(cfg.glossary) == 0 {
		return ""
	}
	claimTokens := tokenize.TokenizeV2(claim)
	c := carrier{claim: map[string]bool{}, crossLang: cross, translations: glossaryIndex(cfg.glossary)}
	for _, t := range claimTokens {
		c.claim[t] = true
	}
	// A claim that restates an exclusion or is negated states no inclusion.
	if len(excludedGroups(claimTokens)) > 0 || boundOrNegation(claimTokens) {
		return ""
	}
	universal := false
	for _, t := range claimTokens {
		if _, ok := universalWords[t]; ok {
			universal = true
		}
	}
	for _, s := range sentenceBreak.Split(softJoin(eu.Text), -1) {
		for _, g := range excludedGroups(tokenize.TokenizeV2(s)) {
			all, known := true, true
			for _, w := range g {
				has, ok := c.carried(w)
				if !ok {
					known = false
					break
				}
				if !has {
					all = false
				}
			}
			if !known {
				continue
			}
			if all || universal {
				return fmt.Sprintf("exclusion guard: the passage excludes %q", strings.Join(g, " "))
			}
		}
	}
	return ""
}

func boundOrNegation(tokens []string) bool {
	for _, t := range tokens {
		switch t {
		case "niet", "not", "geen", "no", "never", "nooit":
			return true
		}
	}
	return false
}
