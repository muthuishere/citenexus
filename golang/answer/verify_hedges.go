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
// for "kan", "at most" for "maximaal"), is not refused. Can only refuse.

package answer

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/muthuishere/citenexus/golang/gate"
	"github.com/muthuishere/citenexus/golang/tokenize"
)

var absolutizers = [][]string{
	{"altijd"}, {"always"}, {"steeds"}, {"at", "any", "time"}, {"op", "elk", "moment"}, {"whenever"},
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
	for _, h := range hedgePhrases {
		for _, sp := range findSpans(tokens, h.words) {
			// "mogen geen", "may not", "kan niet": a prohibition, not a hedge.
			if h.class == hedgePermission {
				negated := false
				for k := sp.end; k < len(tokens) && k <= sp.end+1; k++ {
					if _, neg := markers[tokens[k]]; neg {
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

var toSameAmount = regexp.MustCompile(`\b(?:to|tot)\s*(?:€|eur\b)?\s*[0-9]`)

var totAmount = regexp.MustCompile(`\btot\s*(?:€|eur\b|[0-9][0-9.,]*\s*(?:%|euro\b|procent\b))`)

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
	c := carrier{claim: map[string]bool{}, crossLang: cross, translations: glossaryIndex(cfg.glossary)}
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
	for _, class := range []string{hedgePermission, hedgeUpper, hedgeSoftener} {
		word, ok := unitHedges[class]
		if !ok {
			continue
		}
		if _, kept := claimHedges[class]; kept {
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
