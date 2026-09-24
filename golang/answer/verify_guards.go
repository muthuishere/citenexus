// Deterministic guards for model-admitted claims, and quote extraction.
//
// A SupportChecker may admit a claim the token gate could not verify (a
// translation, a paraphrase). These guards run on every such admission and the
// model cannot override them: numbers, negation and names are exactly where an
// entailment model is weakest and a wrong answer is most expensive. Each guard
// can only REFUSE — none can admit a claim.

package answer

import (
	"fmt"
	"regexp"
	"strings"
	"unicode"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

// numberGuard: every number in the claim is a number in the passage, compared
// by ADR-0015 key (ReadNumber) — each side read in ITS OWN declared language, so
// an English "1,500" over a Dutch "1.500" matches, and "25,00" matches "25".
// A number neither language can resolve ("1.500" undeclared) matches only the
// same spelling: ambiguity refuses, it never guesses.
//
// The passage side also reads SPELLED-OUT numbers: policy text writes small
// numbers as words ("één vakantiedag"), and a true "1 day" was being refused.
// Cardinals come from numberWords, minus "een" — it is also the article "a",
// and reading it as 1 would let any "1" through. Ordinal words ("eerste",
// "first") satisfy only an ORDINAL in the claim ("1st", "1e"), never a bare
// "1": "1 dag" and "de eerste dag" are different facts.
func numberGuard(claim, claimLanguage, passage, passageLanguage string) string {
	have := map[string]struct{}{}
	for _, m := range numbersIn(passage, passageLanguage) {
		have[m.reading.Key] = struct{}{}
		if _, ordinal := ordinalSuffixes[m.unit]; ordinal && m.attached {
			have["ord:"+m.reading.Key] = struct{}{}
		}
	}
	for _, word := range unitScan.FindAllString(strings.ToLower(passage), -1) {
		if value, ok := numberWords[word]; ok && word != "een" {
			have[value] = struct{}{}
		}
		if value, ok := ordinalWords[word]; ok {
			have["ord:"+value] = struct{}{}
		}
	}
	for _, m := range numbersIn(claim, claimLanguage) {
		key := m.reading.Key
		if _, ordinal := ordinalSuffixes[m.unit]; ordinal && m.attached {
			key = "ord:" + key
		}
		if _, ok := have[key]; !ok {
			return fmt.Sprintf("number guard: %s is not in the passage", strings.TrimPrefix(strings.TrimPrefix(key, "ord:"), "?"))
		}
	}
	return ""
}

// ordinalSuffixes follow a digit to make it an ordinal: 1st, 2nd, 3rd, 4th,
// 1e, 2de, 8ste.
var ordinalSuffixes = map[string]struct{}{"st": {}, "nd": {}, "rd": {}, "th": {}, "e": {}, "de": {}, "ste": {}}

// ordinalWords are spelled-out ordinals, NL + EN, 1–12.
var ordinalWords = map[string]string{
	"eerste": "1", "tweede": "2", "derde": "3", "vierde": "4", "vijfde": "5", "zesde": "6",
	"zevende": "7", "achtste": "8", "negende": "9", "tiende": "10", "elfde": "11", "twaalfde": "12",
	"first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "sixth": "6",
	"seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10", "eleventh": "11", "twelfth": "12",
}

// negationGuard: a claim that carries a polarity marker needs a passage that
// carries one. "Any marker", not "the same marker", so it holds across
// languages whose markers are both tabled (EN "not" over NL "niet").
//
// One-directional by design: a passage negation the claim dropped cannot be
// localised in a long passage without an alignment, so that direction is left
// to the checker's contradiction score and the veto.
func negationGuard(claim, passage string) string {
	markers := gate.PolarityMarkers()
	claimNegated := false
	for _, tok := range tokenize.TokenizeV2(claim) {
		if _, ok := markers[tok]; ok {
			claimNegated = true
			break
		}
	}
	if !claimNegated {
		return ""
	}
	for _, tok := range tokenize.TokenizeV2(passage) {
		if _, ok := markers[tok]; ok {
			return ""
		}
	}
	return "negation guard: the claim is negated and the passage is not"
}

// names are the claim's capitalised words that are not in an INITIAL position,
// plus any word mixing letters and digits or written in capitals ("R-119",
// "CAO").
//
// Initial positions (capitalised by typography, not because they are names):
// the start, after a sentence terminator or a colon, after a list marker
// ("-", "*", "•", "1.", "1)", "#"), and right after an opening quote or bracket.
// Markdown emphasis is removed first, so "**Label:** You …" reads "Label: You".
// Treating those as names refused true claims: "- The …", "**Note:** You …"
// were 39 of 66 English name refusals in rag_go's run.
func names(claim string) []string {
	out := []string{}
	plain := strings.NewReplacer("**", "", "__", "", "`", "").Replace(claim)
	initial := true
	for _, f := range strings.Fields(plain) {
		if isListMarker(f) {
			initial = true
			continue
		}
		if f == "|" {
			initial = true // a table cell starts like a sentence
			continue
		}
		opensQuote := strings.IndexAny(f, `"“„«([{'‘`) == 0
		word := strings.Trim(f, `"“”„«»()[]{},;:.!?'‘’|`)
		// Possessive: "Ploum's" names Ploum; the tokenizer would add an "s".
		word = strings.TrimSuffix(strings.TrimSuffix(word, "'s"), "’s")
		// A hyphenated word whose capitalised parts are all lowercase ("e-mail")
		// names nothing; one with a capitalised part stays whole here and falls
		// back to its capitalised parts in nameGuardWith.
		if strings.Contains(word, "-") && len(capitalisedParts(word)) == 0 &&
			!strings.ContainsAny(word, "0123456789") {
			initial = false
			continue
		}
		runes := []rune(word)
		if ordinalToken.MatchString(strings.ToLower(word)) {
			initial = false
			continue // "1st", "2de": a number, not a name
		}
		if len(runes) > 1 {
			hasDigit, hasLetter, allUpper := false, false, true
			for _, r := range runes {
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
			switch {
			case hasLetter && hasDigit, hasLetter && allUpper:
				out = append(out, word)
			case !initial && !opensQuote && unicode.IsUpper(runes[0]):
				out = append(out, word)
			}
		}
		// A terminator or colon ends a sentence or label; the next word is initial.
		trimmed := strings.TrimRight(f, `"”»)]}'’`)
		initial = strings.HasSuffix(trimmed, ".") || strings.HasSuffix(trimmed, "!") ||
			strings.HasSuffix(trimmed, "?") || strings.HasSuffix(trimmed, ":") ||
			strings.HasSuffix(trimmed, ";") || strings.HasSuffix(trimmed, "|")
	}
	return out
}

var ordinalToken = regexp.MustCompile(`^[0-9]+(st|nd|rd|th|e|de|ste)$`)

var listMarker = regexp.MustCompile(`^([-*•·–—]|#{1,6}|[0-9]{1,3}[.)]|[a-z][.)])$`)

// isListMarker is a bullet, heading hash or list number standing alone.
func isListMarker(field string) bool { return listMarker.MatchString(field) }

// nameGuard: every name in the claim is present in the passage.
//
// Deliberately strict across languages: a model paraphrase swapping one
// employer, law or form for another is the expensive failure, a refused true
// claim the cheap one. Three narrow, closed escapes:
//
//   - months and weekdays fold NL <-> EN ("January" <-> "januari"); a swapped
//     month still refuses;
//   - the caller's aliases (VerifyOptions.NameAliases, e.g. "gdpr" -> "avg"):
//     a claim name is present when any alias is. Injected, never guessed;
//   - guards() passes the unit's DocumentID along with its text, so a company
//     named in the document title ("Ploum") is present even when the body says
//     "werkgever".
func nameGuard(claim, passage string) string { return nameGuardWith(claim, passage, nil) }

func nameGuardWith(claim, passage string, aliases map[string][]string) string {
	have := map[string]struct{}{}
	for _, tok := range tokenize.TokenizeV2(passage) {
		have[tok] = struct{}{}
		if folded, ok := calendarFold[tok]; ok {
			have[folded] = struct{}{}
		}
	}
	present := func(tok string) bool {
		if _, ok := have[tok]; ok {
			return true
		}
		if folded, ok := calendarFold[tok]; ok {
			if _, ok := have[folded]; ok {
				return true
			}
		}
		for _, alias := range aliases[tok] {
			for _, at := range tokenize.TokenizeV2(alias) {
				if _, ok := have[at]; ok {
					return true
				}
			}
		}
		return false
	}
	allPresent := func(text string) bool {
		for _, tok := range tokenize.TokenizeV2(text) {
			if !present(tok) {
				return false
			}
		}
		return true
	}
	for _, name := range names(claim) {
		// "Wwft-related": the whole word first, then only its capitalised parts
		// ("Wwft"). A word with digits stays whole ("104-week").
		if strings.Contains(name, "-") && !allPresent(name) && !strings.ContainsAny(name, "0123456789") {
			if parts := capitalisedParts(name); len(parts) > 0 && allPresent(strings.Join(parts, " ")) {
				continue
			}
		}
		if alts, ok := aliases[strings.ToLower(name)]; ok {
			found := false
			for _, alt := range alts {
				all := true
				for _, at := range tokenize.TokenizeV2(alt) {
					if _, ok := have[at]; !ok {
						all = false
						break
					}
				}
				if all {
					found = true
					break
				}
			}
			if found {
				continue
			}
		}
		for _, tok := range tokenize.TokenizeV2(name) {
			if !present(tok) {
				return fmt.Sprintf("name guard: %q is not in the passage", name)
			}
		}
	}
	return ""
}

// capitalisedParts are the hyphen-separated parts starting with a capital.
func capitalisedParts(word string) []string {
	parts := []string{}
	for _, part := range strings.Split(word, "-") {
		if r := []rune(part); len(r) > 0 && unicode.IsUpper(r[0]) {
			parts = append(parts, part)
		}
	}
	return parts
}

// calendarFold maps English month and weekday names to Dutch, both directions,
// to ONE canonical form (the Dutch). Closed on purpose.
var calendarFold = func() map[string]string {
	pairs := [][2]string{
		{"january", "januari"}, {"february", "februari"}, {"march", "maart"}, {"april", "april"},
		{"may", "mei"}, {"june", "juni"}, {"july", "juli"}, {"august", "augustus"},
		{"september", "september"}, {"october", "oktober"}, {"november", "november"}, {"december", "december"},
		{"monday", "maandag"}, {"tuesday", "dinsdag"}, {"wednesday", "woensdag"}, {"thursday", "donderdag"},
		{"friday", "vrijdag"}, {"saturday", "zaterdag"}, {"sunday", "zondag"},
	}
	out := map[string]string{}
	for _, p := range pairs {
		out[p[0]] = p[1]
		out[p[1]] = p[1]
	}
	return out
}()

// guards runs every deterministic guard and returns the first refusal, or "".
func guards(claim, claimLanguage string, eu EvidenceUnit, aliases map[string][]string) string {
	if reason := numberGuard(claim, claimLanguage, eu.Text, eu.Language); reason != "" {
		return reason
	}
	if reason := unitGuard(claim, claimLanguage, eu.Text, eu.Language); reason != "" {
		return reason
	}
	for _, g := range []func(string, string) string{negationGuard, clauseNegationGuard, polaritySwapGuard, qualifierGuard, scopeGuard} {
		if reason := g(claim, eu.Text); reason != "" {
			return reason
		}
	}
	return nameGuardWith(claim, eu.Text+"\n"+eu.DocumentID, aliases)
}

// quotePattern matches double-quoted spans in the common typographic styles.
// Single quotes are not quotes here: they collide with apostrophes.
var quotePattern = regexp.MustCompile(`"([^"]+)"|“([^”]+)”|„([^”“]+)[”“]|«([^»]+)»`)

// MinQuoteTokens is the shortest span that counts as a quote. A one- or
// two-word "quote" anchors nothing.
const MinQuoteTokens = 3

// quotes returns the claim's quoted spans that are long enough to anchor it.
func quotes(claim string) []string {
	out := []string{}
	for _, m := range quotePattern.FindAllStringSubmatch(claim, -1) {
		for _, g := range m[1:] {
			if g != "" && len(tokenize.TokenizeV2(g)) >= MinQuoteTokens {
				out = append(out, g)
			}
		}
	}
	return out
}

// clauseBreak ends a clause: sentence punctuation followed by space or end, a
// comma followed by space ("25,50" is not a break), a dash used as a clause
// separator (— / – anywhere, "-" only between spaces), or a newline.
var clauseBreak = regexp.MustCompile(`[.!?;:]+(\s|$)|,\s|\s*[\x{2014}\x{2013}]\s*|\s-\s|\n`)

// coordinators start a NEW coordinated clause: a polarity marker after one
// belongs to that clause, not to the words the claim matched ("… te verbeteren
// en de ongeschiktheid niet …"). Only the tail AFTER the matched words is cut at
// them; the passage is never split on them, because a claim may itself span one
// ("de reis- en parkeerkosten") and splitting would switch the guard off.
var coordinators = map[string]struct{}{
	"en": {}, "maar": {}, "of": {}, "want": {}, "dus": {},
	"and": {}, "but": {}, "or": {}, "so": {},
}

// clauseNegationGuard closes a hole in the ADR-0009 predicate for verb-final
// languages. gate.IsSupportedV2 inspects polarity markers only INSIDE the
// matched span, so "De werkgever vergoedt de parkeerkosten." passes against
// "De werkgever vergoedt de parkeerkosten niet." — the negation sits after the
// last matched token. It is the ordinary Dutch word order, not an edge case.
//
// For each clause of the passage the claim aligns within:
//
//   - every marker INSIDE the matched span must survive into the claim with its
//     multiplicity (the gate's own rule — repeated here because the model path
//     admits claims the gate never saw);
//   - a marker in the TAIL — at most MaxSingleGap tokens after the span, cut at
//     the first coordinator — must appear in the claim at least once. A claim
//     that already carries the same negation is not refused for it (rag_go
//     R-123 / R-126).
//
// Scoped this narrowly because a wider tail refused true claims: a "zonder" in
// the next clause (G-S4), "geen" after a dash (R-103), "niet" after "en" (G-D3).
// A claim that aligns within no single clause is left to the gate. Can only
// refuse.
func clauseNegationGuard(claim, passage string) string {
	markers := gate.PolarityMarkers()
	claimTokens := tokenize.TokenizeV2(claim)
	inClaim := map[string]int{}
	for _, tok := range claimTokens {
		if _, ok := markers[tok]; ok {
			inClaim[tok]++
		}
	}
	for _, clause := range clauseBreak.Split(passage, -1) {
		clauseTokens := tokenize.TokenizeV2(clause)
		span, ok := gate.Align(claimTokens, clauseTokens)
		if !ok {
			continue
		}
		inSpan := map[string]int{}
		for _, tok := range clauseTokens[span.Start : span.End+1] {
			if _, ok := markers[tok]; ok {
				inSpan[tok]++
			}
		}
		for tok, n := range inSpan {
			if inClaim[tok] < n {
				return fmt.Sprintf("negation guard: the claim drops %q from the matched words", tok)
			}
		}
		tail := clauseTokens[span.End+1:]
		if len(tail) > gate.MaxSingleGap {
			tail = tail[:gate.MaxSingleGap]
		}
		for _, tok := range tail {
			if _, stop := coordinators[tok]; stop {
				break
			}
			if _, ok := markers[tok]; ok && inClaim[tok] == 0 {
				return fmt.Sprintf("negation guard: the passage clause carries %q after the matched words", tok)
			}
		}
	}
	return ""
}
