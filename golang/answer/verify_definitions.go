// The definition guard: a claim that uses the generic noun for a subtype the
// unit DEFINES explicitly.
//
// "Tijdens verlof bouw je geen vakantiedagen op" over "Een werknemer kan
// onbetaald verlof (hierna: het Verlof) opnemen … Tijdens het Verlof bouwt de
// werknemer geen vakantiedagen op" (rag_go triage L-R23): in the unit "het
// Verlof" is unpaid leave; the claim widens it to all leave.
//
// Only EXPLICIT definitions are read — no capitalisation heuristic:
//
//   - "<qualifier> <noun> (hierna: het <Term>)", "(hierna te noemen …)",
//     "(hereinafter: …)", "(hereinafter referred to as …)", "…, hierna 'Term'";
//   - "Onder <qualifier> <noun> wordt verstaan …".
//
// A claim that uses the noun (in one language, or its glossary translation)
// without the qualifier, and does not write the defined Term itself mid-
// sentence ("het Verlof"), is refused. Across languages both words must be in
// VerifyOptions.Glossary, else no verdict. On by default;
// VerifyOptions.DisableDefinitions turns it off. Can only refuse.

package answer

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/muthuishere/citenexus/golang/tokenize"
)

var (
	definedAfter = regexp.MustCompile(`(\p{L}+)\s+(\p{L}+)\s*\(\s*(?:hierna(?:\s+te\s+noemen)?|hereinafter(?:\s+referred\s+to\s+as)?)\s*[:,]?\s*(?:het|de|the)?\s*['‘"“]?(\p{L}+)['’"”]?\s*\)`)
	definedQuote = regexp.MustCompile(`(\p{L}+)\s+(\p{L}+)\s*,?\s*hierna\s+['‘"“](\p{L}+)['’"”]`)
	definedUnder = regexp.MustCompile(`(?i)\bonder\s+(\p{L}+)\s+(\p{L}+)\s+wordt\s+verstaan`)
)

type definition struct{ qualifier, noun, term string }

func definitionsIn(text string) []definition {
	var out []definition
	for _, re := range []*regexp.Regexp{definedAfter, definedQuote} {
		for _, m := range re.FindAllStringSubmatch(text, -1) {
			q, n, term := strings.ToLower(m[1]), strings.ToLower(m[2]), m[3]
			if strings.ToLower(term) != n || !partyWord(q) {
				continue // the Term names the noun it qualifies, or it is not read
			}
			out = append(out, definition{q, n, term})
		}
	}
	for _, m := range definedUnder.FindAllStringSubmatch(text, -1) {
		if partyWord(strings.ToLower(m[1])) {
			out = append(out, definition{strings.ToLower(m[1]), strings.ToLower(m[2]), ""})
		}
	}
	return out
}

// definitionGuard: see the file comment.
func definitionGuard(claim, claimLanguage string, eu EvidenceUnit, cfg guardConfig) string {
	if cfg.noDefinitions {
		return ""
	}
	defs := definitionsIn(eu.Text)
	if len(defs) == 0 {
		return ""
	}
	cross := claimLanguage != "" && eu.Language != "" && primaryLanguage(claimLanguage) != primaryLanguage(eu.Language)
	if cross && len(cfg.glossary) == 0 {
		return ""
	}
	c := carrier{claim: map[string]bool{}, crossLang: cross, translations: glossaryIndex(cfg.glossary)}
	for _, t := range tokenize.TokenizeV2(claim) {
		c.claim[t] = true
	}
	words := listLeadToken.FindAllString(claim, -1)
	for _, d := range defs {
		hasNoun, nounKnown := c.carried(d.noun)
		if !nounKnown || !hasNoun {
			continue
		}
		hasQual, qualKnown := c.carried(d.qualifier)
		if !qualKnown || hasQual {
			continue
		}
		// The defined Term written as such, not at the start of a sentence.
		if d.term != "" {
			written := false
			for i, w := range words {
				if i > 0 && strings.Trim(w, `.,;:!?"'()`) == d.term {
					written = true
				}
			}
			if written {
				continue
			}
		}
		return fmt.Sprintf("definition guard: the passage defines %q as %q", d.noun, d.qualifier+" "+d.noun)
	}
	return ""
}
