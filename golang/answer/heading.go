// Headings a host must not exempt from verification.
//
// VerifyAnswer itself exempts nothing: a Markdown heading is a claim like any
// other line, and an uncited one is refused. Hosts that serve an answer with
// its layout — rag_go's post-pass — exempt refused lines that make no factual
// assertion (headings, lead-ins, greetings), because tearing them out mangles a
// true answer. A heading can assert a rule, though, and an exempt heading is
// served UNCHECKED: "De werkgever moet de reiskosten voorschieten" over a
// werknemer passage, or "Bezwaar via het UWV" over a kantonrechter passage,
// would reach the reader as written.
//
// A host asks two questions before it exempts a heading:
//
//	if claim, _ := answer.HeadingNeedsCheck(line, lang); claim {
//		// keep VerifyAnswer's verdict: the heading is a claim
//	} else if reason := answer.HeadingNameUnsupported(line, evidence, aliases); reason != "" {
//		// refuse it with reason: it names something no unit mentions
//	} else {
//		// exempt: served unchecked
//	}
//
// Both can only turn an exemption into a refusal; neither admits anything.

package answer

import (
	"fmt"
	"regexp"
	"strings"
	"unicode"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

// HeadingRules are the closed word tables HeadingNeedsCheckWith reads, keyed by
// primary language subtag ("nl", "en"). A heading in a language with no entry
// (or undeclared) is read against every language's table. Entries are
// lowercase; a phrase ("recht op") matches as consecutive tokens.
type HeadingRules struct {
	// Modals are obligation / permission words and phrases ("moet", "recht op",
	// "must"). A modal that is also a month or weekday ("May") counts only when
	// written in lowercase.
	Modals map[string][]string
	// Exclusives restrict to one case ("alleen", "only").
	Exclusives map[string][]string
	// Verbs are finite verbs; one of them plus more than VerbWords words makes
	// a heading a sentence that states something.
	Verbs map[string][]string
	// VerbWords is the word count a verb-bearing heading must EXCEED. Zero
	// means DefaultHeadingVerbWords.
	VerbWords int
}

// DefaultHeadingVerbWords: "Wat je krijgt bij ziekte" (5 words) stays a
// heading; a sixth word with a verb makes it a sentence.
const DefaultHeadingVerbWords = 5

// DefaultHeadingRules is the nl/en table rag_go's measurement used (602 exempt
// headings: 8 modal, 0 exclusive, 15 verb-bearing over 5 words; numbers were
// already claims in its post-pass). Hosts supply their own through
// HeadingNeedsCheckWith.
var DefaultHeadingRules = HeadingRules{
	Modals: map[string][]string{
		"nl": {"mag", "mogen", "moet", "moeten", "verplicht", "verplichte", "recht op"},
		"en": {"must", "may", "shall", "entitled"},
	},
	Exclusives: map[string][]string{
		"nl": {"alleen", "uitsluitend", "enkel", "slechts"},
		"en": {"only", "solely", "exclusively"},
	},
	Verbs: map[string][]string{
		"nl": {"is", "zijn", "wordt", "worden", "heeft", "hebben", "krijgt", "krijg", "krijgen",
			"geldt", "gelden", "kan", "kun", "kunt", "kunnen", "betaalt", "betalen", "valt", "vallen",
			"blijft", "blijven", "gaat", "gaan", "loopt", "telt", "vervalt", "ontvang", "ontvangt",
			"bouw", "bouwt", "neem", "neemt"},
		"en": {"is", "are", "has", "have", "can", "will", "get", "gets", "applies", "apply", "pays",
			"pay", "counts", "remains", "stays", "receive", "receives", "take", "takes", "need",
			"needs", "does", "do"},
	},
}

// HeadingNeedsCheck reports whether a line a host would exempt as a heading
// states a rule, and so must stay a claim with VerifyAnswer's verdict. It does:
// when it carries a modal or obligation word, an exclusivity word, a number
// (a digit or a number word other than the article "een"/"one"), or a finite
// verb and more than DefaultHeadingVerbWords words. language is the answer's
// declared language ("nl", "en-GB"; "" reads every table). reason names the
// trigger ("heading states a rule: modal \"moet\"").
func HeadingNeedsCheck(heading, language string) (claim bool, reason string) {
	return HeadingNeedsCheckWith(heading, language, DefaultHeadingRules)
}

// HeadingNeedsCheckWith is HeadingNeedsCheck with the host's own tables; they
// replace the defaults entirely. Numbers are always read.
func HeadingNeedsCheckWith(heading, language string, rules HeadingRules) (claim bool, reason string) {
	text := headingText(heading)
	words := listLeadToken.FindAllString(text, -1)
	tokens := tokenize.TokenizeV2(text)
	capitalised := map[string]bool{} // tokens written ONLY capitalised
	lowered := map[string]bool{}
	for _, w := range words {
		for _, tok := range tokenize.TokenizeV2(w) {
			if r := []rune(strings.Trim(w, "\"'“”‘’()[]{}.,;:!?")); len(r) > 0 && unicode.IsUpper(r[0]) {
				capitalised[tok] = true
			} else {
				lowered[tok] = true
			}
		}
	}
	lang := primaryLanguage(language)
	if w, ok := matchTable(tokens, tableFor(rules.Modals, lang), func(w string) bool {
		_, calendar := calendarFold[w]
		return calendar && capitalised[w] && !lowered[w]
	}); ok {
		return true, fmt.Sprintf("heading states a rule: modal %q", w)
	}
	if w, ok := matchTable(tokens, tableFor(rules.Exclusives, lang), nil); ok {
		return true, fmt.Sprintf("heading states a rule: exclusive %q", w)
	}
	for _, tok := range tokens {
		if strings.ContainsAny(tok, "0123456789") {
			return true, fmt.Sprintf("heading states a rule: number %q", tok)
		}
		if _, ok := numberWords[tok]; ok && tok != "een" && tok != "one" {
			return true, fmt.Sprintf("heading states a rule: number %q", tok)
		}
	}
	limit := rules.VerbWords
	if limit == 0 {
		limit = DefaultHeadingVerbWords
	}
	if len(tokens) > limit {
		if w, ok := matchTable(tokens, tableFor(rules.Verbs, lang), nil); ok {
			return true, fmt.Sprintf("heading states a rule: verb %q in %d words", w, len(tokens))
		}
	}
	return false, ""
}

// HeadingNameUnsupported returns a refusal reason when the heading names
// something — a name as the name guard reads it — that appears in NONE of the
// evidence units (their text or DocumentID; aliases as VerifyOptions.NameAliases).
// "" means every name is somewhere in the evidence.
//
// Capitalisation is only a name signal where the writer had a choice. So:
//   - a table row ("| Soort Verlof | Duur |") starts every cell like a
//     sentence: a capitalised cell word is not a name;
//   - a Title Case heading ("Bijzonder Verlof En Permanente Educatie") — every
//     word capitalised except function words — carries no signal: only
//     acronyms ("UWV") and words mixing letters and digits ("R-119") count;
//   - the first word is never a name by case alone.
//
// And it is only a swap cover: a name the evidence mentions anywhere passes,
// in any case, so a common word capitalised in a heading ("Juist") passes when
// the evidence uses it.
func HeadingNameUnsupported(heading string, evidence []EvidenceUnit, aliases map[string][]string) string {
	text := headingText(heading)
	found := names(text)
	if titleCase(text) {
		kept := found[:0:0]
		for _, n := range found {
			if strong(n) {
				kept = append(kept, n)
			}
		}
		found = kept
	}
	if len(found) == 0 {
		return ""
	}
	var all strings.Builder
	for _, eu := range evidence {
		all.WriteString(eu.Text)
		all.WriteString("\n")
		all.WriteString(eu.DocumentID)
		all.WriteString("\n")
	}
	if name := absentName(found, all.String(), aliases); name != "" {
		return fmt.Sprintf("heading name guard: %q is in no evidence unit", name)
	}
	return ""
}

var headingMarker = regexp.MustCompile(`^\s*(?:#{1,6}\s+|>\s*|(?:[-*•·]|[0-9]{1,3}[.)])\s+)*`)

// headingText is the heading as a reader sees it: markup and a leading heading,
// quote or list marker removed.
func headingText(heading string) string {
	return strings.TrimSpace(headingMarker.ReplaceAllString(stripMarkup(heading), ""))
}

func tableFor(table map[string][]string, lang string) []string {
	if entries, ok := table[lang]; ok {
		return entries
	}
	all := []string{}
	for _, entries := range table {
		all = append(all, entries...)
	}
	return all
}

// matchTable: the first entry (a word or a phrase) found in tokens, skipping a
// single-word match skip() rejects.
func matchTable(tokens, entries []string, skip func(string) bool) (string, bool) {
	for _, entry := range entries {
		et := tokenize.TokenizeV2(entry)
		if len(et) == 0 {
			continue
		}
		for i := 0; i+len(et) <= len(tokens); i++ {
			if !equalTokens(tokens[i:i+len(et)], et) {
				continue
			}
			if len(et) == 1 && skip != nil && skip(et[0]) {
				continue
			}
			return entry, true
		}
	}
	return "", false
}

// titleCase: at least two words, and every word that is not a function word
// starts with a capital.
func titleCase(text string) bool {
	capitals := 0
	for _, w := range listLeadToken.FindAllString(text, -1) {
		bare := strings.Trim(w, "\"'“”‘’()[]{}.,;:!?|")
		r := []rune(bare)
		if len(r) == 0 || !unicode.IsLetter(r[0]) {
			continue
		}
		if unicode.IsUpper(r[0]) {
			capitals++
			continue
		}
		low := strings.ToLower(bare)
		if _, stop := contextStop[low]; stop || gate.IsStopword(low) {
			continue
		}
		return false
	}
	return capitals >= 2
}

// strong: a name by its form, not its case — an acronym or letters with digits.
func strong(name string) bool {
	hasDigit, hasLetter, allUpper := false, false, true
	for _, r := range name {
		switch {
		case unicode.IsDigit(r):
			hasDigit = true
		case unicode.IsLetter(r):
			hasLetter = true
			if !unicode.IsUpper(r) {
				allUpper = false
			}
		}
	}
	return hasLetter && (hasDigit || allUpper)
}
