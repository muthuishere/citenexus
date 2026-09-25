// VerifyOptions.ConjunctPresence: the cross-language condition reading of
// 65ee10d + 2130dd0 + bec3c77, off by default.
//
// Across languages the condition guard judges a word missing through the
// caller's glossary. A glossary lists some translations, not every
// rendering, so a claim that states a condition of its own may render the
// source's in words the glossary does not list ("toestemming → permission"
// under "with the consent of"). With ConjunctPresence on:
//
//   - NO-VERDICT BRANCH: for a cross-language claim that states a condition of
//     its own (crossConditionMarkers), a glossary can SATISFY a condition word
//     but never show it missing (carrier.satisfyOnly).
//   - PER-CONJUNCT PRESENCE: that branch must not pass a partial condition.
//     The unit's condition is split into conjuncts (droppedConjunct); when
//     the claim's own condition has fewer parts than the unit's, every
//     conjunct must be positively PRESENT — a word of it the claim carries
//     (the same token, a number or a name, a glossary translation). A
//     conjunct nothing shows present, including one the glossary cannot see
//     at all, counts as missing: "te goeder trouw en naar behoren melden"
//     under a claim that keeps only good faith is refused. A claim whose
//     condition has as many parts keeps the no-verdict.
//
// It trades recall on renderings for catching unseen dropped conjuncts: a
// compressed claim that states every conjunct in one part ("a shelf stacker
// under 21 who works on Sunday") is refused when one conjunct has no
// glossary sense. The number/name conjunct check (verify_conjuncts.go) runs
// either way, after this one: a claim refused here is never reported twice.

package answer

import (
	"regexp"
	"strings"
	"unicode"

	"github.com/muthuishere/citenexus/golang/tokenize"
)

var crossConditionMarkers = [][]string{
	{"if"}, {"when"}, {"whenever"}, {"once"}, {"provided"}, {"unless"}, {"as", "long", "as"}, {"who"},
	{"whose"}, {"which"}, {"that"}, {"with"}, {"without"}, {"after"}, {"before"}, {"on"}, {"only"},
	{"except"}, {"subject", "to"}, {"where"}, {"in", "case"},
	{"als"}, {"wanneer"}, {"indien"}, {"mits"}, {"zodra"}, {"zolang"}, {"tenzij"}, {"die"}, {"dat"},
	{"met"}, {"zonder"}, {"na"}, {"op"}, {"alleen"}, {"behalve"}, {"bij"},
}

var presenceOpener = regexp.MustCompile(`(?i)\b(mits|indien|tenzij|zolang|wanneer|als|die|op voorwaarde dat|provided that|provided|unless|if|when|once|who)\b`)

var presenceSplit = regexp.MustCompile(`(?i),|\b(?:zowel|both|as well as)\b|\b(?:en|and)\b`)

var presenceCoordinator = regexp.MustCompile(`(?i)\b(?:en|and|zowel|both|as well as)\b`)

var presenceTotEnMet = regexp.MustCompile(`(?i)\btot en met\b`)

// presenceFunctionWords: pronouns and have-auxiliaries of four letters or
// more are no part of a conjunct ("heeft", "they").
var presenceFunctionWords = map[string]bool{
	"they": true, "them": true, "their": true, "have": true, "been": true, "would": true, "could": true,
	"should": true, "hebben": true, "heeft": true, "zich": true, "deze": true, "werd": true,
	"werden": true, "zullen": true, "zouden": true,
}

// droppedConjunct: the unit sentence's conjunctive condition (after its first
// opener, without a final main-clause comma segment) against the claim.
// Returns a word of a conjunct the claim does not positively carry and the
// conjunct count, when the claim's own condition has fewer conjuncts than
// the unit's. sentenceLanguage: the unit's declared language.
func droppedConjunct(claim, sentence, sentenceLanguage string, c carrier) (string, int) {
	loc := presenceOpener.FindStringIndex(sentence)
	if loc == nil {
		return "", 0
	}
	// "zowel … als" is a coordination, not a condition.
	if m := strings.ToLower(sentence[loc[0]:loc[1]]); m == "als" && strings.Contains(strings.ToLower(sentence[:loc[0]]), "zowel") {
		return "", 0
	}
	before := map[string]bool{}
	for _, t := range tokenize.TokenizeV2(sentence[:loc[0]]) {
		before[t] = true
	}
	span := presenceTotEnMet.ReplaceAllString(sentence[loc[1]:], "tot_en_met")
	// Final comma segments without a coordinator are the main clause (after a
	// sentence-initial condition or a relative clause) or trailing material,
	// not conjuncts. "mits A, B en C, krijgt X" keeps "A, B en C".
	segs := strings.Split(span, ",")
	for len(segs) > 1 && !presenceCoordinator.MatchString(segs[len(segs)-1]) {
		segs = segs[:len(segs)-1]
	}
	var conjuncts [][]string
	for _, p := range presenceSplit.Split(strings.Join(segs, ","), -1) {
		var ws []string
		for _, t := range tokenize.TokenizeV2(p) {
			if conditionContent(t) && !presenceFunctionWords[t] && !before[t] {
				ws = append(ws, t)
			}
		}
		if len(ws) > 0 {
			conjuncts = append(conjuncts, ws)
		}
	}
	n := len(conjuncts)
	if n < 2 {
		return "", 0
	}
	// A Dutch subordinate clause ends in its verb, and coordinated adverbials
	// share it: in "te goeder trouw en naar behoren meldt" the verb belongs
	// to both, not to "naar behoren" alone — counted there, a claim's
	// "reports" would make the dropped "naar behoren" look present.
	if primaryLanguage(sentenceLanguage) == "nl" {
		if last := conjuncts[n-1]; len(last) >= 2 && isWord(last[len(last)-1]) {
			conjuncts[n-1] = last[:len(last)-1] // a verb is a word, never a number
		}
	}
	absent := ""
	for _, ws := range conjuncts {
		present := false
		for _, w := range ws {
			if has, _ := c.carried(w); has {
				present = true
				break
			}
		}
		if !present && absent == "" {
			absent = ws[0]
		}
	}
	if absent == "" {
		return "", 0
	}
	// The claim's own condition: from its first condition marker on.
	lc := strings.ToLower(claim)
	cl := presenceOpener.FindStringIndex(lc)
	if cl == nil {
		for _, m := range []string{" with ", " met ", " after ", " na ", " on ", " op "} {
			if i := strings.Index(lc, m); i >= 0 {
				cl = []int{i, i + len(m)}
				break
			}
		}
	}
	if cl == nil {
		return "", 0
	}
	if m := len(presenceSplit.Split(presenceTotEnMet.ReplaceAllString(lc[cl[1]:], "tot_en_met"), -1)); m >= n {
		return "", 0 // as many conditions as the unit: may be all of them, in other words
	}
	return absent, n
}

func isWord(t string) bool {
	for _, r := range t {
		if !unicode.IsLetter(r) {
			return false
		}
	}
	return t != ""
}
