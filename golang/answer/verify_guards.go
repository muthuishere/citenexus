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
	"math/big"
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
	// Clock times first, compared as times; then blanked for the rest.
	claimClocks, claim := clockTimes(claim)
	passageClocks, passage := clockTimes(passage)
	// Dates next, compared as dates, then blanked.
	claimDates, claim := datesIn(claim, claimLanguage)
	passageDates, passage := datesIn(passage, passageLanguage)
	for _, cd := range claimDates {
		found := false
		for _, pd := range passageDates {
			if sameDate(cd, pd) {
				found = true
				break
			}
		}
		if !found {
			return fmt.Sprintf("number guard: %s is not in the passage", cd)
		}
	}
	for _, k := range sortedKeys(claimClocks) {
		if _, ok := passageClocks[k]; !ok {
			return fmt.Sprintf("number guard: %s is not in the passage", strings.TrimPrefix(k, "clock:"))
		}
	}
	have := map[string]struct{}{}
	for _, m := range numbersIn(passage, passageLanguage) {
		have[centsAsEuros(m)] = struct{}{}
		if _, ordinal := ordinalSuffixes[m.unit]; ordinal && m.attached {
			have["ord:"+m.reading.Key] = struct{}{}
		}
	}
	for _, word := range unitScan.FindAllString(strings.ToLower(passage), -1) {
		if value, ok := numberWordValue(word); ok && word != "een" {
			have[value] = struct{}{}
		}
		if value, ok := ordinalWords[word]; ok {
			have["ord:"+value] = struct{}{}
		}
	}
	for _, m := range numbersIn(claim, claimLanguage) {
		key := centsAsEuros(m)
		if _, ordinal := ordinalSuffixes[m.unit]; ordinal && m.attached {
			key = "ord:" + key
		}
		if _, ok := have[key]; !ok {
			return fmt.Sprintf("number guard: %s is not in the passage", strings.TrimPrefix(strings.TrimPrefix(key, "ord:"), "?"))
		}
	}
	// A spelled-out COUNT in the claim is refused only against a CONFLICTING
	// count: the passage puts a different number before the same noun ("op
	// twee manieren" over "op drie manieren"). Reading every claim number word
	// as a number to find refused 31 of 1,626 true claims in rag_go's data
	// ("two options" over a passage listing both; Dutch "ten minste") and caught
	// no leak. A number word before a time unit is a period — the unit guard's.
	if reason := countConflict(claim, passage, passageLanguage); reason != "" {
		return reason
	}
	return ""
}

// countConflict: a number word in the claim, followed by a noun, where the
// passage counts that same noun only with other values. "een"/"one" are never a
// count (article, pronoun); a following time unit makes it a period.
func countConflict(claim, passage, passageLanguage string) string {
	words := unitScan.FindAllString(strings.ToLower(claim), -1)
	ptoks := unitScan.FindAllString(strings.ToLower(passage), -1)
	for i, word := range words {
		value, ok := numberWordValue(word)
		if !ok || word == "een" || word == "one" || i+1 >= len(words) {
			continue
		}
		noun := words[i+1]
		if _, function := countFunctionWords[noun]; function {
			continue // "één voor één", "two of the …": not a counted noun
		}
		if _, _, period := unitOf(noun); period {
			continue
		}
		if _, isNumber := numberValue(noun, passageLanguage); isNumber {
			continue
		}
		// An inflected adjective ("drie opvolgende maanden") is not the thing
		// counted: compare adjective and noun together.
		span := []string{noun}
		if strings.HasSuffix(noun, "e") && i+2 < len(words) {
			span = append(span, words[i+2])
		}
		var others []string
		agrees := false
		for k := 0; k+len(span) < len(ptoks); k++ {
			if !equalTokens(ptoks[k+1:k+1+len(span)], span) || ptoks[k] == "een" || ptoks[k] == "one" {
				continue
			}
			pv, isNumber := numberValue(ptoks[k], passageLanguage)
			if !isNumber {
				continue
			}
			if pv == value {
				agrees = true
			} else {
				others = append(others, ptoks[k])
			}
		}
		if !agrees && len(others) > 0 {
			return fmt.Sprintf("number guard: %s %s, the passage says %s %s", word, noun, others[0], noun)
		}
	}
	return ""
}

// countFunctionWords follow a number without being what it counts.
var countFunctionWords = map[string]struct{}{
	"voor": {}, "na": {}, "van": {}, "op": {}, "in": {}, "of": {}, "en": {}, "per": {},
	"uit": {}, "bij": {}, "tot": {}, "met": {}, "aan": {}, "keer": {},
	"for": {}, "the": {}, "and": {}, "or": {}, "to": {}, "times": {}, "at": {}, "by": {},
}

func equalTokens(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
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
	claimTokens := tokenize.TokenizeV2(claim)
	// "no later than" / "niet meer dan" state a BOUND, not a negation — but only
	// when the passage bounds the same way ("uiterlijk", "maximaal"). Over an
	// opposite bound or no bound at all their "no"/"niet" still counts.
	bounded := boundMarkerPositions(claimTokens, boundDirections(tokenize.TokenizeV2(passage)))
	claimNegated := false
	for i, tok := range claimTokens {
		if _, ok := markers[tok]; ok && !bounded[i] {
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
		if _, ok := negativeWords[tok]; ok {
			return "" // "Unused budget" carries the negation of "Niet gebruikt budget"
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
		if _, code := currencyCodes[strings.ToLower(word)]; code {
			initial = false
			continue // "EUR 2.40": a currency, read with its amount, not a name
		}
		if ordinalToken.MatchString(strings.ToLower(word)) || numberWithUnit.MatchString(strings.ToLower(word)) {
			initial = false
			continue // "1st", "2de", "25-jarig", "40-hour", "1/12th": a number, not a name
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

// numberWithUnit is a number joined to its unit or a fraction: "25-jarig",
// "40-urige", "40-hour", "3-year", "1/12th", "1/12e". The number and unit
// guards read them; they are not names.
var numberWithUnit = regexp.MustCompile(`^[0-9]+([.,][0-9]+)?-?(jarig|jarige|urig|urige|daags|daagse|weeks|weekse|maands|maandse|hour|hours|day|days|week|weeks|month|months|year|years)$|^[0-9]+/[0-9]+(st|nd|rd|th|e|de|ste)?$|^[0-9]{1,2}([:.][0-5][0-9])?(am|pm)$`)

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
	if name := absentName(names(claim), passage, aliases); name != "" {
		return fmt.Sprintf("name guard: %q is not in the passage", name)
	}
	return ""
}

// absentName is the first of names not present in passage ("" when all are),
// by the name guard's rules: tokens, calendar folding, the caller's aliases,
// and a hyphenated word's capitalised parts.
func absentName(names []string, passage string, aliases map[string][]string) string {
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
		// An alias counts only when EVERY one of its words is present: "ov" ->
		// "openbaar vervoer" must not be satisfied by "eigen vervoer".
		for _, alias := range aliases[tok] {
			words := tokenize.TokenizeV2(alias)
			all := len(words) > 0
			for _, at := range words {
				if _, ok := have[at]; !ok {
					all = false
					break
				}
			}
			if all {
				return true
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
	for _, name := range names {
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
				return name
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
// guardConfig is the caller's configuration the guards read.
type guardConfig struct {
	aliases map[string][]string
	actors  ActorLexicon
	pairs   []QualifierPair
	verbs   []VerbPair
	// gloss: the prepared glossary (glossary.go); nil reads as empty.
	gloss *PreparedGlossary
	// noDefinitions: VerifyOptions.DisableDefinitions. docDefs: every
	// explicit definition in the evidence, by DocumentID.
	noDefinitions bool
	docDefs       map[string][]definition
	subtypes      []SubtypeHead
	// fragment: the text is a list lead-in checked on its own (union rule):
	// it states no fact, so the hedge guard does not read it.
	fragment bool
}

func guards(claim, claimLanguage string, eu EvidenceUnit, cfg guardConfig) string {
	aliases, actors, pairs := cfg.aliases, cfg.actors, cfg.pairs
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
	if reason := roleGuard(claim, claimLanguage, eu, actors); reason != "" {
		return reason
	}
	if reason := relationGuard(claim, claimLanguage, eu, actors); reason != "" {
		return reason
	}
	// A claim that is a cut span of a unit sentence whose restriction follows
	// (P1) is refused on every path, not only after the gate: the model admits
	// such prefixes at P(E) >= 0.99.
	if reason := truncationGuard(claim, eu.Text); reason != "" {
		return reason
	}
	if reason := exclusionGuard(claim, claimLanguage, eu, cfg); reason != "" {
		return reason
	}
	if reason := hedgeGuard(claim, claimLanguage, eu, cfg); reason != "" {
		return reason
	}
	if reason := verbPairGuard(claim, claimLanguage, eu, cfg.verbs, cfg); reason != "" {
		return reason
	}
	if reason := definitionGuard(claim, claimLanguage, eu, cfg); reason != "" {
		return reason
	}
	if reason := subtypeGuard(claim, eu, cfg); reason != "" {
		return reason
	}
	if reason := conditionGuard(claim, claimLanguage, eu, cfg); reason != "" {
		return reason
	}
	if reason := qualifierPairGuard(claim, claimLanguage, eu, pairs); reason != "" {
		return reason
	}
	if reason := partySwapGuard(claim, eu.Text, actors); reason != "" {
		return reason
	}
	if reason := subjectSwapGuard(claim, claimLanguage, eu, cfg); reason != "" {
		return reason
	}
	if reason := valueRowGuard(claim, claimLanguage, eu); reason != "" {
		return reason
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
		// In span order, so the reason names the same marker on every run.
		for _, tok := range clauseTokens[span.Start : span.End+1] {
			if n, ok := inSpan[tok]; ok && inClaim[tok] < n {
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

// restrictiveTail open a clause-internal continuation that narrows what came
// before it: a preposition, a relative, a condition. NL + EN; "up to" is two
// tokens.
var restrictiveTail = map[string]struct{}{
	"met": {}, "van": {}, "voor": {}, "tot": {}, "boven": {}, "onder": {}, "bij": {}, "aan": {},
	"zonder": {}, "behalve": {}, "uitgezonderd": {}, "alleen": {}, "uitsluitend": {},
	"mits": {}, "tenzij": {}, "indien": {}, "als": {}, "wanneer": {}, "die": {}, "dat": {}, "waarvan": {},
	// Not "of": in Dutch it is "or" ("via HR of via de vertrouwenspersoon").
	"with": {}, "for": {}, "above": {}, "below": {}, "over": {}, "provided": {},
	"unless": {}, "if": {}, "when": {}, "who": {}, "that": {}, "which": {},
	"without": {}, "except": {}, "only": {},
}

// truncationGuard runs after every gate admission and inside guards() (every
// model, quote and union admission), and refuses outright. The gate (gate.IsSupportedV2,
// ADR-0009) admits a claim that is a verbatim span of a unit sentence, and a
// span can stop exactly where the sentence restricts it: "Medewerkers mogen
// geen geschenken aannemen." over "… aannemen met een waarde van meer dan
// € 50." Admitted as "gate", no guard or model ever saw it.
//
// For every clause of the passage the claim aligns within, it looks at the
// clause's next word after the aligned span: a restrictive word (a preposition,
// a relative, a condition — restrictiveTail, or "up to") means that clause
// narrows the claim. There is no verdict when ANY clause it aligns in does not
// continue that way (it ends there, or a new clause starts: ", en …"), or when
// it aligns in no single clause. Otherwise the claim is REFUSED: the source
// states the restriction explicitly, and the model admits such cut prefixes
// at P(E) >= 0.99 (rag_go adv dh-v2-05/09/17/29).
//
// It lives here, above the gate, on purpose: the gate predicate is pinned
// byte for byte in Python, Go and JS by conformance vectors, and this check is
// Go-only VerifyAnswer behaviour. It is a candidate for a cross-port ADR-0009
// amendment later.
func truncationGuard(claim, passage string) string {
	claimTokens := tokenize.TokenizeV2(claim)
	restricted := ""
	for _, clause := range clauseBreak.Split(softJoin(passage), -1) {
		clauseTokens := tokenize.TokenizeV2(clause)
		span, ok := gate.Align(claimTokens, clauseTokens)
		if !ok {
			continue
		}
		tail := clauseTokens[span.End+1:]
		next := ""
		if len(tail) > 0 {
			next = tail[0]
		}
		_, narrows := restrictiveTail[next]
		if next == "up" && len(tail) > 1 && tail[1] == "to" {
			narrows, next = true, "up to"
		}
		if next == "in" && len(tail) > 2 && tail[1] == "so" && tail[2] == "far" {
			narrows, next = true, "in so far as"
		}
		if !narrows {
			return "" // a clause that states the claim as it is
		}
		if restricted == "" {
			restricted = next
		}
	}
	if restricted == "" {
		return ""
	}
	return fmt.Sprintf("truncation guard: the claim omits a restriction the source attaches (%q)", restricted)
}

// Bounds: phrases that set an upper or a lower limit, NL + EN. A phrase that
// starts with a polarity marker ("no later than", "niet meer dan") reads as
// a negation to the negation guard unless the passage bounds the same way.
const (
	boundUpper = "upper"
	boundLower = "lower"
)

var boundPhrases = []struct {
	words     []string
	direction string
}{
	{[]string{"no", "later", "than"}, boundUpper}, {[]string{"not", "later", "than"}, boundUpper},
	{[]string{"no", "more", "than"}, boundUpper}, {[]string{"not", "more", "than"}, boundUpper},
	{[]string{"at", "most"}, boundUpper}, {[]string{"up", "to"}, boundUpper},
	{[]string{"niet", "later", "dan"}, boundUpper}, {[]string{"niet", "meer", "dan"}, boundUpper},
	{[]string{"uiterlijk"}, boundUpper}, {[]string{"maximaal"}, boundUpper}, {[]string{"hooguit"}, boundUpper},
	{[]string{"ten", "hoogste"}, boundUpper}, {[]string{"maximum"}, boundUpper},
	{[]string{"no", "earlier", "than"}, boundLower}, {[]string{"not", "earlier", "than"}, boundLower},
	{[]string{"no", "less", "than"}, boundLower}, {[]string{"not", "less", "than"}, boundLower},
	{[]string{"no", "fewer", "than"}, boundLower}, {[]string{"at", "least"}, boundLower},
	{[]string{"niet", "eerder", "dan"}, boundLower}, {[]string{"niet", "minder", "dan"}, boundLower},
	{[]string{"minimaal"}, boundLower}, {[]string{"ten", "minste"}, boundLower},
	{[]string{"tenminste"}, boundLower}, {[]string{"minimum"}, boundLower},
}

// boundDirections are the bound directions present in tokens.
func boundDirections(tokens []string) map[string]bool {
	out := map[string]bool{}
	for _, b := range boundPhrases {
		if len(findSpans(tokens, b.words)) > 0 {
			out[b.direction] = true
		}
	}
	return out
}

// boundMarkerPositions: the token positions of bound phrases in the claim
// whose direction the passage also has — their markers are not negations.
func boundMarkerPositions(tokens []string, passage map[string]bool) map[int]bool {
	out := map[int]bool{}
	for _, b := range boundPhrases {
		if !passage[b.direction] {
			continue
		}
		for _, sp := range findSpans(tokens, b.words) {
			for i := sp.start; i < sp.end; i++ {
				out[i] = true
			}
		}
	}
	return out
}

// centsAsEuros is a number's key, with an amount in cents read in euros:
// "23 cent" = "€ 0,23" (key 0.23). "23 euro" stays 23, so a cent-euro swap
// refuses.
func centsAsEuros(m numberMatch) string {
	switch m.unit {
	case "cent", "cents", "ct", "eurocent", "eurocents":
		if m.reading.Value != nil {
			return ratKey(new(big.Rat).Quo(m.reading.Value, big.NewRat(100, 1)))
		}
	}
	return m.reading.Key
}

// currencyCodes are ISO codes a claim writes for the euro sign ("EUR 2.40").
var currencyCodes = map[string]struct{}{"eur": {}, "usd": {}, "gbp": {}}

// negativeWords carry a negation in the word itself; a negated claim ("niet
// gebruikt") over a passage that has one ("unused") is not refused for the
// missing marker. Passage side only; closed on purpose.
var negativeWords = map[string]struct{}{
	"unused": {}, "unpaid": {}, "untaken": {}, "unclaimed": {}, "unspent": {},
	"ongebruikt": {}, "ongebruikte": {}, "onbetaald": {}, "onbetaalde": {}, "onopgenomen": {},
}
