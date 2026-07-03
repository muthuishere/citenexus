// Package chunker is the pinned CiteNexus recursive chunker (SPEC-PORTS-v1 §4).
//
// Definition (frozen contract): a recursive, boundary-aware splitter. "Token"
// count is the whitespace-split word count. Defaults max_tokens=450,
// overlap=60. Parity with the Python reference
// citenexus.evidence.chunker.chunk_text.
//
// Boundary order (coarsest first): paragraph (/\n\s*\n/), line (/\n/), sentence
// (whitespace immediately following . ! or ?). A single oversized word-run is
// hard-split into consecutive max_tokens-word windows. Pieces are then greedily
// packed into max_tokens chunks joined by "\n", carrying a trailing whole-piece
// overlap window between chunks.
package chunker

import (
	"regexp"
	"strings"
	"unicode"
)

const (
	DefaultMaxTokens = 450
	DefaultOverlap   = 60
)

var paragraphRE = regexp.MustCompile(`\n\s*\n`)

// tokens counts whitespace-split words (Python str.split()).
func tokens(text string) int {
	return len(strings.Fields(text))
}

// splitSentences mirrors Python re.split(`(?<=[.!?])\s+`, text): it splits on
// each maximal whitespace run that immediately follows a . ! or ?, consuming the
// whitespace and keeping the punctuation on the left piece. RE2 has no
// lookbehind, so this is done by scanning.
func splitSentences(text string) []string {
	rs := []rune(text)
	var out []string
	start := 0
	i := 0
	for i < len(rs) {
		if unicode.IsSpace(rs[i]) {
			j := i
			for j < len(rs) && unicode.IsSpace(rs[j]) {
				j++
			}
			if i > 0 && (rs[i-1] == '.' || rs[i-1] == '!' || rs[i-1] == '?') {
				out = append(out, string(rs[start:i]))
				start = j
			}
			i = j
		} else {
			i++
		}
	}
	out = append(out, string(rs[start:]))
	return out
}

// stripDrop strips each piece and drops empties.
func stripDrop(pieces []string) []string {
	out := make([]string, 0, len(pieces))
	for _, p := range pieces {
		s := strings.TrimSpace(p)
		if s != "" {
			out = append(out, s)
		}
	}
	return out
}

// splitUnits splits text on the coarsest boundary that yields more than one
// non-empty piece; finest fallback is individual words.
func splitUnits(text string) []string {
	for _, pieces := range [][]string{
		stripDrop(paragraphRE.Split(text, -1)),
		stripDrop(strings.Split(text, "\n")),
		stripDrop(splitSentences(text)),
	} {
		if len(pieces) > 1 {
			return pieces
		}
	}
	return strings.Fields(text)
}

// fitPieces recursively splits text until every piece fits maxTokens.
func fitPieces(text string, maxTokens int) []string {
	if tokens(text) <= maxTokens {
		return []string{text}
	}
	units := splitUnits(text)
	if len(units) == 1 {
		words := strings.Fields(units[0])
		var out []string
		for i := 0; i < len(words); i += maxTokens {
			end := i + maxTokens
			if end > len(words) {
				end = len(words)
			}
			out = append(out, strings.Join(words[i:end], " "))
		}
		return out
	}
	var out []string
	for _, unit := range units {
		out = append(out, fitPieces(unit, maxTokens)...)
	}
	return out
}

// overlapTail returns the trailing pieces whose combined word-count is within
// overlap tokens.
func overlapTail(pieces []string, overlap int) []string {
	if overlap <= 0 {
		return nil
	}
	var tail []string
	size := 0
	for i := len(pieces) - 1; i >= 0; i-- {
		n := tokens(pieces[i])
		if size+n > overlap {
			break
		}
		tail = append([]string{pieces[i]}, tail...)
		size += n
	}
	return tail
}

// pack greedily packs pieces into maxTokens chunks joined by "\n", carrying an
// overlap tail between chunks.
func pack(pieces []string, maxTokens, overlap int) []string {
	chunks := []string{}
	var current []string
	size := 0
	for _, piece := range pieces {
		n := tokens(piece)
		if len(current) > 0 && size+n > maxTokens {
			chunks = append(chunks, strings.Join(current, "\n"))
			tail := overlapTail(current, overlap)
			current = append([]string(nil), tail...)
			size = 0
			for _, p := range current {
				size += tokens(p)
			}
		}
		current = append(current, piece)
		size += n
	}
	if len(current) > 0 {
		chunks = append(chunks, strings.Join(current, "\n"))
	}
	return chunks
}

// ChunkText splits text into bounded, overlapping, boundary-respecting chunks.
// It panics if maxTokens < 1 (the Python reference raises ValueError).
func ChunkText(text string, maxTokens, overlap int) []string {
	if maxTokens < 1 {
		panic("max_tokens must be >= 1")
	}
	text = strings.TrimSpace(text)
	if text == "" {
		return []string{}
	}
	if tokens(text) <= maxTokens {
		return []string{text}
	}
	if overlap < 0 {
		overlap = 0
	}
	if overlap > maxTokens-1 {
		overlap = maxTokens - 1
	}
	pieces := fitPieces(text, maxTokens)
	return pack(pieces, maxTokens, overlap)
}
