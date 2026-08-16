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

// Python's str.lower() applies Unicode *full* case mapping; Go's strings.ToLower
// uses *simple* (1:1) mapping. They agree everywhere that matters to the ASCII
// [a-z0-9] tokenizer EXCEPT U+0130 (İ, Latin capital I with dot above): Python
// lowers it to "i" + U+0307 (combining dot above), splitting the ASCII run into
// two tokens, while Go's simple map drops the dot and yields a bare "i" glued to
// the following letters. Pre-expand İ to reproduce the reference exactly.
// (Conformance: the multilingual anti-drift corpus, ADR-0006.)
var fullCaseLower = strings.NewReplacer("İ", "i̇")

// Tokenize lowercases text (matching Python str.lower's full case mapping) and
// returns all ASCII [a-z0-9]+ runs, in order. A string with no alphanumeric
// runs yields an empty (non-nil) slice.
func Tokenize(text string) []string {
	toks := tokenRE.FindAllString(strings.ToLower(fullCaseLower.Replace(text)), -1)
	if toks == nil {
		return []string{}
	}
	return toks
}
