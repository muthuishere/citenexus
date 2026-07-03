// Package euid is the pinned CiteNexus Evidence-Unit id + block builder
// (SPEC-PORTS-v1 §4). It mirrors the Python reference
// citenexus.evidence.builder / chunked_builder / chunker exactly.
//
// Block builder: each ordered block whose text is non-empty after trimming maps
// to one unit with eu_id "{document_id}::{order}"; empty/whitespace-only blocks
// are skipped. Chunked builder splits each surviving block via the recursive
// chunker into child units "{document_id}::{order}::{i}". Checksum is the
// lowercase-hex SHA-256 of the raw UTF-8 bytes.
package euid

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"regexp"
	"strings"
)

// Block is one extracted block. Only order + text drive id assignment.
type Block struct {
	Order int    `json:"order"`
	Text  string `json:"text"`
}

// BlockBuilderEUIDs maps each non-empty block to one eu_id "{document_id}::{order}",
// in document order, skipping blocks whose text is empty or whitespace-only.
func BlockBuilderEUIDs(documentID string, blocks []Block) []string {
	ids := []string{}
	for _, b := range blocks {
		if strings.TrimSpace(b.Text) == "" {
			continue
		}
		ids = append(ids, fmt.Sprintf("%s::%d", documentID, b.Order))
	}
	return ids
}

// ChunkedBuilderEUIDs chunks each non-empty block into child eu_ids
// "{document_id}::{order}::{i}", in document order.
func ChunkedBuilderEUIDs(documentID string, blocks []Block, maxTokens, overlap int) []string {
	ids := []string{}
	for _, b := range blocks {
		if strings.TrimSpace(b.Text) == "" {
			continue
		}
		chunks := ChunkText(b.Text, maxTokens, overlap)
		for i := range chunks {
			ids = append(ids, fmt.Sprintf("%s::%d::%d", documentID, b.Order, i))
		}
	}
	return ids
}

// Checksum is the lowercase-hex SHA-256 of the raw UTF-8 bytes.
func Checksum(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(sum[:])
}

// --- recursive chunker (mirror of citenexus.evidence.chunker) ---

var (
	reParagraph = regexp.MustCompile(`\n\s*\n`)
	reLine      = regexp.MustCompile(`\n`)
)

func tokens(text string) int { return len(strings.Fields(text)) }

// splitSentence emulates Python re.split(r"(?<=[.!?])\s+", text): break on each
// whitespace run that is preceded by a sentence-ending punctuation.
func splitSentence(text string) []string {
	runes := []rune(text)
	var res []string
	start, i := 0, 0
	for i < len(runes) {
		if isASCIISpace(runes[i]) && i > 0 && isSentenceEnd(runes[i-1]) {
			res = append(res, string(runes[start:i]))
			for i < len(runes) && isASCIISpace(runes[i]) {
				i++
			}
			start = i
			continue
		}
		i++
	}
	res = append(res, string(runes[start:]))
	return res
}

func isASCIISpace(r rune) bool {
	switch r {
	case ' ', '\t', '\n', '\r', '\f', '\v':
		return true
	}
	return false
}

func isSentenceEnd(r rune) bool { return r == '.' || r == '!' || r == '?' }

func stripFilter(pieces []string) []string {
	out := []string{}
	for _, p := range pieces {
		if s := strings.TrimSpace(p); s != "" {
			out = append(out, s)
		}
	}
	return out
}

// splitUnits splits on the coarsest boundary (paragraph, line, sentence) that
// yields more than one piece; else falls back to individual words.
func splitUnits(text string) []string {
	if pieces := stripFilter(reParagraph.Split(text, -1)); len(pieces) > 1 {
		return pieces
	}
	if pieces := stripFilter(reLine.Split(text, -1)); len(pieces) > 1 {
		return pieces
	}
	if pieces := stripFilter(splitSentence(text)); len(pieces) > 1 {
		return pieces
	}
	return strings.Fields(text)
}

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
	for _, u := range units {
		out = append(out, fitPieces(u, maxTokens)...)
	}
	return out
}

func overlapTail(pieces []string, overlap int) []string {
	if overlap <= 0 {
		return []string{}
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

func pack(pieces []string, maxTokens, overlap int) []string {
	var chunks []string
	var current []string
	size := 0
	for _, piece := range pieces {
		n := tokens(piece)
		if len(current) > 0 && size+n > maxTokens {
			chunks = append(chunks, strings.Join(current, "\n"))
			tail := overlapTail(current, overlap)
			current = append([]string{}, tail...)
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
	if overlap > maxTokens-1 {
		overlap = maxTokens - 1
	}
	if overlap < 0 {
		overlap = 0
	}
	pieces := fitPieces(text, maxTokens)
	return pack(pieces, maxTokens, overlap)
}
