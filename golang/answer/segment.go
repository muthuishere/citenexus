// Guarded claim segmentation (ADR-0009, ADR-0010 tier 1).
//
// An answer is decomposed into atomic claims so each can be verified against its
// cited passage independently. Splitting on punctuation alone is not good
// enough: the naive `[.!?\n]+` splitter failed 54.2% of the ADR-0009 spike's
// six-language cases — abbreviations, decimals and CJK terminators all break it.
//
// This is tier-1 scanning code over a tier-2 table (segmentation.json, a copy of
// conformance/segmentation.json, embedded so the module is self-contained as a
// Go dependency). Adding `。！？` to the *table* fixed 100% of the Japanese
// failures with no algorithm change, which is why claim segmentation stays
// native per port rather than moving to the Rust core.
//
// Portability notes, both load-bearing and both why this is a hand-written
// scanner with NO regex at all:
//
//   - Python's `re.escape` emits `\!`, which is a COMPILE ERROR in Go's RE2, so
//     a regex ported character class would not even build here.
//   - `\s` is Unicode-aware in Python but ASCII-only in RE2. Whitespace is
//     spelled out explicitly below so the ports cannot diverge.
//
// Two further Go-specific parity requirements, neither visible in the Python
// source: Python indexes strings by CODE POINT (Go indexes by byte, so the
// scanner runs over []rune), and Python's `str.strip()` uses the Unicode
// whitespace set of `str.isspace`, which is NOT the same as Go's
// `strings.TrimSpace`/`unicode.IsSpace` (Python includes U+001C–U+001F, Go does
// not). pyStrip below reproduces Python's set exactly.
package answer

import (
	_ "embed"
	"encoding/json"
	"strings"
	"sync"
	"unicode"
)

//go:embed segmentation.json
var segmentationJSON []byte

// Spelled out rather than a `\s` class — see the package doc. This is the
// whitespace set the SPLITTER consults (rule 4 and preceding-word scanning); it
// is deliberately the same short set as the Python reference's _WHITESPACE, and
// is NOT the (wider) set used to trim a finished claim.
const segWhitespace = " \t\n\r\f\v\u00a0\u3000"

// Terminators that require whitespace (or end-of-text) after them to count as a
// break. CJK and Arabic/Indic terminators break unconditionally, because those
// scripts do not put a space after the mark.
const needsTrailingSpace = ".!?"

var (
	segOnce       sync.Once
	terminators   map[rune]struct{}
	abbreviations map[string]struct{}
)

func loadSegmentationTable() (map[rune]struct{}, map[string]struct{}) {
	segOnce.Do(func() {
		var table struct {
			Terminators   []string `json:"terminators"`
			Abbreviations []string `json:"abbreviations"`
		}
		if err := json.Unmarshal(segmentationJSON, &table); err != nil {
			panic("answer: unmarshal segmentation.json: " + err.Error())
		}
		terminators = make(map[rune]struct{}, len(table.Terminators))
		for _, t := range table.Terminators {
			for _, r := range t {
				terminators[r] = struct{}{}
			}
		}
		abbreviations = make(map[string]struct{}, len(table.Abbreviations))
		for _, a := range table.Abbreviations {
			abbreviations[a] = struct{}{}
		}
	})
	return terminators, abbreviations
}

// pyIsSpace reports whether r is whitespace to Python's str.isspace — the set
// str.strip() trims. Go's unicode.IsSpace omits U+001C–U+001F, which Python
// includes, so trimming with strings.TrimSpace would silently diverge.
func pyIsSpace(r rune) bool {
	switch r {
	case '\t', '\n', '\v', '\f', '\r', 0x1c, 0x1d, 0x1e, 0x1f, ' ',
		0x85, 0xa0, 0x1680, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000:
		return true
	}
	return r >= 0x2000 && r <= 0x200a
}

// pyStrip is Python's str.strip() with no argument.
func pyStrip(s string) string {
	return strings.TrimFunc(s, pyIsSpace)
}

func isSegWhitespace(r rune) bool {
	return strings.ContainsRune(segWhitespace, r)
}

func isASCIIDigit(r rune) bool {
	return r >= '0' && r <= '9'
}

// precedingWord is the token immediately before the terminator run, lowercased.
func precedingWord(buffer []rune, terms map[rune]struct{}) string {
	text := buffer
	for len(text) > 0 {
		if _, isTerm := terms[text[len(text)-1]]; !isTerm {
			break
		}
		text = text[:len(text)-1]
	}
	start := len(text)
	for start > 0 && !isSegWhitespace(text[start-1]) {
		start--
	}
	// Python's str.lower() applies Unicode FULL case mapping; Go's
	// strings.ToLower applies simple 1:1 mapping. They differ on U+0130 (İ),
	// which Python lowers to "i"+U+0307 (two code points, so it is not a
	// single-letter initial) while Go yields a bare "i" (which WOULD be read as
	// an initial and suppress a break). Pre-expand it, exactly as the tokenizer
	// does, so the initial-detection rule cannot diverge.
	return strings.ToLower(fullCaseLower.Replace(string(text[start:])))
}

var fullCaseLower = strings.NewReplacer("\u0130", "i\u0307")

// SplitClaims splits text into atomic claims on guarded sentence boundaries.
// Deterministic: the same text always yields the same claims.
//
// Rules, applied in order and all local to the break candidate:
//
//  1. a run of terminators is one candidate boundary, not several;
//  2. no break when the terminator sits between two digits ("500.00");
//  3. no break when the preceding token is a known abbreviation, or a single
//     letter (initials — "J. Smith");
//  4. no break for space-using scripts unless whitespace or end-of-text follows.
//
// A hard line break always ends a claim: pooled evidence and list items are
// newline-joined, and dropping that rule silently merges them into one
// unverifiable claim.
func SplitClaims(text string) []string {
	terms, abbrevs := loadSegmentationTable()

	runes := []rune(text)
	n := len(runes)
	claims := []string{}
	buffer := make([]rune, 0, n)

	for i := 0; i < n; i++ {
		ch := runes[i]
		buffer = append(buffer, ch)

		if ch == '\n' {
			if claim := pyStrip(string(buffer)); claim != "" {
				claims = append(claims, claim)
			}
			buffer = buffer[:0]
			continue
		}

		if _, isTerm := terms[ch]; !isTerm {
			continue
		}

		// rule 1 — consume the whole terminator run ("?!", "...")
		for i+1 < n {
			if _, ok := terms[runes[i+1]]; !ok {
				break
			}
			i++
			buffer = append(buffer, runes[i])
		}

		var following rune // 0 == end of text (Python's "")
		if i+1 < n {
			following = runes[i+1]
		}
		var preceding rune
		if i > 0 {
			preceding = runes[i-1]
		}

		// rule 2 — decimal, e.g. "500.00"
		if isASCIIDigit(preceding) && following != 0 && isASCIIDigit(following) {
			continue
		}

		// rule 3 — abbreviation or initial
		word := precedingWord(buffer, terms)
		if _, isAbbrev := abbrevs[word]; isAbbrev {
			continue
		}
		if wr := []rune(word); len(wr) == 1 && unicode.IsLetter(wr[0]) {
			continue
		}

		// rule 4 — space-using scripts need whitespace or end-of-text
		if following != 0 && !isSegWhitespace(following) && strings.ContainsRune(needsTrailingSpace, ch) {
			continue
		}

		if claim := pyStrip(string(buffer)); claim != "" {
			claims = append(claims, claim)
		}
		buffer = buffer[:0]
	}

	if tail := pyStrip(string(buffer)); tail != "" {
		claims = append(claims, tail)
	}
	return claims
}
