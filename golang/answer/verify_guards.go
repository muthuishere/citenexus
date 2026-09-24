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
func numberGuard(claim, claimLanguage, passage, passageLanguage string) string {
	have := map[string]struct{}{}
	for _, m := range numbersIn(passage, passageLanguage) {
		have[m.reading.Key] = struct{}{}
	}
	for _, m := range numbersIn(claim, claimLanguage) {
		if _, ok := have[m.reading.Key]; !ok {
			return fmt.Sprintf("number guard: %s is not in the passage", strings.TrimPrefix(m.reading.Key, "?"))
		}
	}
	return ""
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

// names are the claim's capitalised words that are not sentence-initial, plus
// any word mixing letters and digits or written in capitals ("R-119", "CAO").
func names(claim string) []string {
	out := []string{}
	fields := strings.FieldsFunc(claim, func(r rune) bool {
		return unicode.IsSpace(r) || strings.ContainsRune(`"“”„«»()[]{},;:`, r)
	})
	initial := true
	for _, f := range fields {
		word := strings.TrimRight(f, ".!?")
		runes := []rune(word)
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
			case !initial && unicode.IsUpper(runes[0]):
				out = append(out, word)
			}
		}
		initial = word != f // a terminator ends a sentence; the next word is initial
	}
	return out
}

// nameGuard: every name in the claim is present in the passage.
//
// Deliberately strict across languages: an English claim naming "Monday" over a
// Dutch "maandag" is refused. That is a false ABSTENTION, which is the cheap
// failure; a model paraphrase swapping one employer, law or form for another is
// the expensive one.
func nameGuard(claim, passage string) string {
	have := map[string]struct{}{}
	for _, tok := range tokenize.TokenizeV2(passage) {
		have[tok] = struct{}{}
	}
	for _, name := range names(claim) {
		for _, tok := range tokenize.TokenizeV2(name) {
			if _, ok := have[tok]; !ok {
				return fmt.Sprintf("name guard: %q is not in the passage", name)
			}
		}
	}
	return ""
}

// guards runs every deterministic guard and returns the first refusal, or "".
func guards(claim, claimLanguage string, eu EvidenceUnit) string {
	if reason := numberGuard(claim, claimLanguage, eu.Text, eu.Language); reason != "" {
		return reason
	}
	for _, g := range []func(string, string) string{negationGuard, clauseNegationGuard, nameGuard} {
		if reason := g(claim, eu.Text); reason != "" {
			return reason
		}
	}
	return ""
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
// comma followed by space ("25,50" is not a break), or a newline.
var clauseBreak = regexp.MustCompile(`[.!?;:]+(\s|$)|,\s|\n`)

// clauseNegationGuard closes a hole in the ADR-0009 predicate for verb-final
// languages. gate.IsSupportedV2 inspects polarity markers only INSIDE the
// matched span, so "De werkgever vergoedt de parkeerkosten." passes against
// "De werkgever vergoedt de parkeerkosten niet." — the negation sits after the
// last matched token. Measured on the Dutch fixtures (feat/nl-tables); it is the
// ordinary Dutch word order, not an edge case.
//
// For each clause of the passage the claim aligns within, every marker in the
// rest of that clause must survive into the claim. Scoped to the clause so a
// negation belonging to the NEXT clause ("…, maar niet de reiskosten") does not
// refuse a true claim. A claim that aligns within no single clause is left to
// the gate. Go-only for now; it can only refuse.
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
		want := map[string]int{}
		for _, tok := range clauseTokens[span.Start:] {
			if _, ok := markers[tok]; ok {
				want[tok]++
			}
		}
		for tok, n := range want {
			if inClaim[tok] < n {
				return fmt.Sprintf("negation guard: the passage clause carries %q after the matched words", tok)
			}
		}
	}
	return ""
}
