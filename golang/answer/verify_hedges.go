// The hedge guard: a claim that states absolutely what the source hedges or
// limits.
//
// The model admits "The company pays an annual bonus of 10%" over "The
// company may pay an annual bonus of up to 10% …", and "You can always follow
// the training during working hours" over "… kan de opleiding in beginsel in
// werktijd volgen" (rag_go adv dropped_hedge). Two deterministic readings,
// with closed NL/EN tables whose classes are language-independent:
//
//   - ABSOLUTE ADDED: the claim carries an absolutizer (altijd, always, at any
//     time, whenever, without restriction, for any reason, ongeacht, in alle
//     gevallen, for as long as needed, …) and the unit carries none. No
//     sentence matching is needed and it holds across languages.
//   - HEDGE DROPPED: the unit sentence the claim follows attaches a hedge —
//     permission/possibility (mag, kan, may, can), an upper bound (maximaal,
//     ten hoogste, hooguit, tot een maximum van, tot + amount, up to, at most,
//     no more than), or a softener (in beginsel, in principe, in de regel,
//     zoveel mogelijk, in principle, as a rule, as far as possible) — and the
//     claim carries no hedge of that class. The sentence is found by shared
//     content words in one language, and across languages by a shared number
//     (the value is language-free) or through VerifyOptions.Glossary; without
//     either, no verdict.
//
// A claim that keeps the hedge, or hedges equally in another language ("may"
// for "kan", "at most" for "maximaal") or another construction ("normaal
// gesproken" for "in principe", "it is possible that" for "kan", "may not …
// more than" for "at most"), is not refused. The guard also runs after every
// gate admission: the gate's alignment may skip a hedge inside a gap. Can only
// refuse.

package answer

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

var absolutizers = [][]string{
	{"altijd"}, {"always"}, {"steeds"}, {"te", "allen", "tijde"}, {"at", "all", "times"}, {"voortdurend"},
	{"at", "any", "time"}, {"op", "elk", "moment"}, {"whenever"},
	{"wanneer", "ze", "maar", "willen"}, {"without", "restriction"}, {"zonder", "beperking"},
	{"for", "any", "reason"}, {"om", "welke", "reden", "dan", "ook"}, {"ongeacht"}, {"regardless"},
	{"in", "alle", "gevallen"}, {"in", "all", "cases"}, {"for", "as", "long", "as", "needed"},
	{"zo", "lang", "als", "nodig"}, {"at", "all"}, {"onbeperkt"}, {"unlimited"},
}

const (
	hedgePermission = "permission"
	hedgeUpper      = "upper bound"
	hedgeSoftener   = "softener"
)

var hedgePhrases = []struct {
	words []string
	class string
}{
	{[]string{"mag"}, hedgePermission}, {[]string{"mogen"}, hedgePermission}, {[]string{"kan"}, hedgePermission},
	{[]string{"kunnen"}, hedgePermission}, {[]string{"kun"}, hedgePermission}, {[]string{"kunt"}, hedgePermission},
	{[]string{"may"}, hedgePermission}, {[]string{"can"}, hedgePermission}, {[]string{"might"}, hedgePermission},
	{[]string{"maximaal"}, hedgeUpper}, {[]string{"ten", "hoogste"}, hedgeUpper}, {[]string{"hooguit"}, hedgeUpper},
	{[]string{"tot", "een", "maximum"}, hedgeUpper}, {[]string{"maximum"}, hedgeUpper}, {[]string{"up", "to"}, hedgeUpper},
	{[]string{"at", "most"}, hedgeUpper}, {[]string{"no", "more", "than"}, hedgeUpper}, {[]string{"capped"}, hedgeUpper},
	{[]string{"in", "beginsel"}, hedgeSoftener}, {[]string{"in", "principe"}, hedgeSoftener},
	{[]string{"in", "de", "regel"}, hedgeSoftener}, {[]string{"zoveel", "mogelijk"}, hedgeSoftener},
	{[]string{"in", "principle"}, hedgeSoftener}, {[]string{"as", "a", "rule"}, hedgeSoftener},
	{[]string{"as", "far", "as", "possible"}, hedgeSoftener}, {[]string{"as", "much", "as", "possible"}, hedgeSoftener},
}

// hedgesIn: the hedge classes in tokens, with "tot" + a money amount or a
// percentage read as an upper bound ("tot € 2.500", "tot 10%"); a range
// ("van 23.00 uur tot 7.30 uur", "tot en met") is not.
func hedgesIn(tokens []string, text string) map[string]string {
	out := map[string]string{}
	markers := gate.PolarityMarkers()
	// A purpose or result clause ("zodat de bedrijfsarts contact kan
	// opnemen", "so that …", "in order to …") does not hedge the main fact.
	for i, t := range tokens {
		if t == "zodat" || t == "opdat" || (t == "so" && i+1 < len(tokens) && tokens[i+1] == "that") ||
			(t == "in" && i+2 < len(tokens) && tokens[i+1] == "order" && tokens[i+2] == "to") {
			tokens = tokens[:i]
			break
		}
	}
	// A negation that opens a split bound ("mag niet hoger zijn dan", "may not
	// borrow more than") limits an amount; it does not negate the modal.
	boundMarker := map[int]bool{}
	for _, b := range splitBounds(tokens) {
		boundMarker[b.marker] = true
		if b.direction == boundUpper {
			if _, seen := out[hedgeUpper]; !seen {
				out[hedgeUpper] = tokens[b.marker] + " … " + "than"
			}
		}
	}
	for _, h := range hedgePhrases {
		for _, sp := range findSpans(tokens, h.words) {
			// A negated modal is a PROHIBITION, like "mogen geen", not a hedge:
			// "kan de werkgever geen rechten ontlenen", "may not". The negation
			// may come a few words on in the same clause.
			if h.class == hedgePermission {
				negated := false
				for k := sp.end; k < len(tokens) && k <= sp.end+4; k++ {
					if _, neg := markers[tokens[k]]; neg && !boundMarker[k] {
						negated = true
					}
				}
				if negated {
					continue
				}
			}
			if _, seen := out[h.class]; !seen {
				out[h.class] = strings.Join(h.words, " ")
			}
		}
	}
	if totAmount.MatchString(strings.ToLower(text)) {
		if _, seen := out[hedgeUpper]; !seen {
			out[hedgeUpper] = "tot"
		}
	}
	return out
}

var claimRange = regexp.MustCompile(`\b[0-9][0-9.,]*\s*(?:tot|to|t/m|-|–)\s*[0-9]|\b(?:tussen|between)\s+[0-9][0-9.,]*\s+(?:en|and)\s+[0-9]`)

var toSameAmount = regexp.MustCompile(`\b(?:to|tot)\s*(?:€|eur\b)?\s*[0-9]`)

var totAmount = regexp.MustCompile(`\btot\s*(?:€|eur\b|[0-9][0-9.,]*\s*(?:%|euro\b|procent\b))`)

// hedgeEquivalents hedge a CLAIM the way the tabled phrases do, in other
// constructions: "normaal gesproken" / "usually" for "in principe"; "het is
// toegestaan" / "is allowed to" / "it is possible that" for "mag" / "kan",
// where the hedge sits on the whole sentence rather than on the verb. They are
// read on the claim side only: a claim that keeps the hedge in other words
// has not dropped it. The unit side stays on the tabled phrases, so these can
// never make the guard refuse more.
var hedgeEquivalents = []struct {
	words []string
	class string
}{
	{[]string{"normaal", "gesproken"}, hedgeSoftener}, {[]string{"normaliter"}, hedgeSoftener},
	{[]string{"gewoonlijk"}, hedgeSoftener}, {[]string{"doorgaans"}, hedgeSoftener},
	{[]string{"meestal"}, hedgeSoftener}, {[]string{"in", "het", "algemeen"}, hedgeSoftener},
	{[]string{"over", "het", "algemeen"}, hedgeSoftener}, {[]string{"als", "regel"}, hedgeSoftener},
	{[]string{"in", "de", "meeste", "gevallen"}, hedgeSoftener}, {[]string{"in", "beginsel"}, hedgeSoftener},
	{[]string{"normally"}, hedgeSoftener}, {[]string{"usually"}, hedgeSoftener},
	{[]string{"generally"}, hedgeSoftener}, {[]string{"in", "general"}, hedgeSoftener},
	{[]string{"typically"}, hedgeSoftener}, {[]string{"ordinarily"}, hedgeSoftener},
	{[]string{"in", "most", "cases"}, hedgeSoftener}, {[]string{"as", "a", "general", "rule"}, hedgeSoftener},
	{[]string{"toegestaan"}, hedgePermission}, {[]string{"mogelijk"}, hedgePermission},
	{[]string{"mogelijkheid"}, hedgePermission}, {[]string{"allowed"}, hedgePermission},
	{[]string{"permitted"}, hedgePermission}, {[]string{"possible"}, hedgePermission},
	{[]string{"option"}, hedgePermission}, {[]string{"optional"}, hedgePermission},
}

// claimHedgeEquivalents: the classes hedgeEquivalents give the claim. A
// negated one ("niet toegestaan", "is not allowed", "no option") is a
// prohibition and gives none.
func claimHedgeEquivalents(tokens []string) map[string]bool {
	markers := gate.PolarityMarkers()
	out := map[string]bool{}
	for _, h := range hedgeEquivalents {
		for _, sp := range findSpans(tokens, h.words) {
			// "zo snel mogelijk", "as soon as possible", "zoveel mogelijk":
			// a degree, not a permission.
			if sp.start >= 1 && (tokens[sp.start-1] == "zoveel" || tokens[sp.start-1] == "zo") {
				continue
			}
			if sp.start >= 2 && (tokens[sp.start-2] == "zo" || tokens[sp.start-2] == "as") {
				continue
			}
			// A permission word hedges the claim only as a predicate ("het is
			// toegestaan", "are allowed to", "it is possible that", "has the
			// option to"), never as an adjective on a noun ("possible next
			// steps are discussed" states the discussion as a fact).
			if h.class == hedgePermission && !predicative(tokens, sp) {
				continue
			}
			negated := false
			for k := sp.start - 3; k < len(tokens) && k <= sp.end+2; k++ {
				if k < 0 || (k >= sp.start && k < sp.end) {
					continue
				}
				if _, neg := markers[tokens[k]]; neg {
					negated = true
				}
			}
			if !negated {
				out[h.class] = true
			}
		}
	}
	return out
}

var permissionCopulas = map[string]struct{}{
	"is": {}, "are": {}, "be": {}, "was": {}, "were": {}, "been": {}, "zijn": {}, "wordt": {}, "worden": {},
	"has": {}, "have": {}, "had": {}, "heeft": {}, "hebben": {}, "biedt": {}, "bieden": {},
}

var permissionComplements = map[string]struct{}{"to": {}, "that": {}, "for": {}, "om": {}, "dat": {}, "te": {}}

func predicative(tokens []string, sp span) bool {
	for k := sp.start - 3; k < sp.start; k++ {
		if k >= 0 {
			if _, ok := permissionCopulas[tokens[k]]; ok {
				return true
			}
		}
	}
	if sp.end < len(tokens) {
		if _, ok := permissionComplements[tokens[sp.end]]; ok {
			return true
		}
	}
	return false
}

func hasAny(tokens []string, phrases [][]string) string {
	for _, p := range phrases {
		if len(findSpans(tokens, p)) > 0 {
			return strings.Join(p, " ")
		}
	}
	return ""
}

// hedgeGuard: see the file comment.
func hedgeGuard(claim, claimLanguage string, eu EvidenceUnit, cfg guardConfig) string {
	if cfg.fragment {
		return "" // a lead-in fragment states no fact of its own
	}
	claimTokens := tokenize.TokenizeV2(claim)
	unitTokens := tokenize.TokenizeV2(eu.Text)
	if a := hasAny(claimTokens, absolutizers); a != "" && hasAny(unitTokens, absolutizers) == "" {
		return fmt.Sprintf("hedge guard: the claim says %q; the source states no such absolute", a)
	}
	cross := claimLanguage != "" && eu.Language != "" && primaryLanguage(claimLanguage) != primaryLanguage(eu.Language)
	c := carrier{claim: map[string]bool{}, crossLang: cross, translations: cfg.gloss.idx()}
	for _, t := range claimTokens {
		c.claim[t] = true
	}
	claimNumbers := map[string]bool{}
	for _, m := range numbersIn(claim, claimLanguage) {
		claimNumbers[m.reading.Key] = true
	}
	// The unit sentence the claim follows: shared content words (through the
	// glossary across languages), or a shared number.
	best, bestN := "", 0
	tie := false
	for _, s := range sentenceBreak.Split(softJoin(eu.Text), -1) {
		n := 0
		seen := map[string]bool{}
		for _, t := range tokenize.TokenizeV2(s) {
			has, _ := c.carried(t)
			if !seen[t] && has && conditionContent(t) {
				seen[t] = true
				n++
			}
		}
		for _, m := range numbersIn(s, eu.Language) {
			if claimNumbers[m.reading.Key] {
				n += 2 // a shared value anchors the sentence in any language
			}
		}
		switch {
		case n > bestN:
			best, bestN, tie = s, n, false
		case n == bestN && n > 0:
			tie = true
		}
	}
	if bestN < 2 || tie {
		return ""
	}
	unitHedges := hedgesIn(tokenize.TokenizeV2(best), best)
	claimHedges := hedgesIn(claimTokens, claim)
	for class := range claimHedgeEquivalents(claimTokens) {
		claimHedges[class] = class
	}
	for _, class := range []string{hedgePermission, hedgeUpper, hedgeSoftener} {
		word, ok := unitHedges[class]
		if !ok {
			continue
		}
		if _, kept := claimHedges[class]; kept {
			continue
		}
		// A range in the claim ("1 tot 3 maanden", "between 1 and 3") states
		// its own bounds.
		if class == hedgeUpper && claimRange.MatchString(strings.ToLower(claim)) {
			continue
		}
		// "aanvullen tot 70%" / "top up to 70%": the claim's "to"/"tot" + the
		// same amount carries the source's "tot".
		if class == hedgeUpper && word == "tot" && toSameAmount.MatchString(strings.ToLower(claim)) {
			continue
		}
		return fmt.Sprintf("hedge guard: the source limits it (%s %q) and the claim states it without", class, word)
	}
	return ""
}
