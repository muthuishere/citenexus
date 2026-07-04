// Package tokenize is the pinned CiteNexus tokenizer (SPEC-PORTS-v1 §4).
//
// Definition (frozen contract): lowercase the input, then return every match of
// [a-z0-9]+ (ASCII only, no stemming). This is the single tokenizer behind
// BM25, the relevance gate, and the faithfulness gate — parity with the Python
// reference citenexus.testing.fakes.tokenize (str.lower() + [a-z0-9]+ findall).
package tokenize

import (
	"regexp"
	"strings"
)

var tokenRE = regexp.MustCompile(`[a-z0-9]+`)

// Tokenize lowercases text (Unicode-aware, matching Python str.lower) and
// returns all ASCII [a-z0-9]+ runs, in order. A string with no alphanumeric
// runs yields an empty (non-nil) slice.
func Tokenize(text string) []string {
	toks := tokenRE.FindAllString(strings.ToLower(text), -1)
	if toks == nil {
		return []string{}
	}
	return toks
}
