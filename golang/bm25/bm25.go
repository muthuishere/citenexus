// Package bm25 is the pinned CiteNexus BM25-lite ranking (SPEC-PORTS-v1 §4/§10).
//
// Definition (frozen contract): tokenize with the pinned §4 tokenizer, take the
// SET of query terms, and score each row with classic BM25 (k1=1.5, b=0.75) over
// a language-agnostic bag of terms. Rows scoring 0 are dropped; the rest are
// sorted DESCENDING by score with a stable tie-break by original input order.
// Parity with the Python reference citenexus.storage.bm25.Bm25TextSearch.
package bm25

import (
	"math"
	"sort"

	"github.com/muthuishere/citenexus-go/tokenize"
)

// Standard BM25 saturation / length-normalization constants.
const (
	k1 = 1.5
	b  = 0.75
)

// Row is one input document: an id and its raw text.
type Row struct {
	EuID string
	Text string
}

// Result is a scored row in ranked order.
type Result struct {
	EuID  string
	Score float64
}

// Rank scores rows against query and returns the ordered (eu_id, score) list,
// dropping zero-score rows. Scores are rounded to 1e-6 to match the fixture.
func Rank(rows []Row, query string) []Result {
	if len(rows) == 0 {
		return []Result{}
	}
	terms := tokenize.Tokenize(query)
	if len(terms) == 0 {
		return []Result{}
	}

	tokenized := make([][]string, len(rows))
	totalLen := 0
	for i, row := range rows {
		toks := tokenize.Tokenize(row.Text)
		tokenized[i] = toks
		totalLen += len(toks)
	}
	nDocs := len(rows)
	avgLen := float64(totalLen) / float64(nDocs)
	if avgLen == 0 {
		avgLen = 1.0
	}

	// SET of query terms, preserving no order (membership only).
	queryTerms := make(map[string]struct{})
	for _, t := range terms {
		queryTerms[t] = struct{}{}
	}

	docFreq := make(map[string]int, len(queryTerms))
	for term := range queryTerms {
		n := 0
		for _, toks := range tokenized {
			if contains(toks, term) {
				n++
				continue
			}
		}
		docFreq[term] = n
	}

	type scored struct {
		score float64
		idx   int
	}
	var results []scored
	for idx, toks := range tokenized {
		counts := make(map[string]int, len(toks))
		for _, t := range toks {
			counts[t]++
		}
		docLen := float64(len(toks))
		score := 0.0
		for term := range queryTerms {
			tf := counts[term]
			if tf == 0 {
				continue
			}
			nT := docFreq[term]
			idf := math.Log(1.0 + (float64(nDocs)-float64(nT)+0.5)/(float64(nT)+0.5))
			norm := float64(tf) * (k1 + 1.0) / (float64(tf) + k1*(1.0-b+b*docLen/avgLen))
			score += idf * norm
		}
		if score > 0.0 {
			results = append(results, scored{score: score, idx: idx})
		}
	}

	// Descending score; stable tie-break by original row order.
	sort.SliceStable(results, func(i, j int) bool {
		return results[i].score > results[j].score
	})

	out := make([]Result, len(results))
	for i, s := range results {
		out[i] = Result{EuID: rows[s.idx].EuID, Score: round6(s.score)}
	}
	return out
}

func contains(toks []string, term string) bool {
	for _, t := range toks {
		if t == term {
			return true
		}
	}
	return false
}

func round6(v float64) float64 {
	return math.Round(v*1e6) / 1e6
}
