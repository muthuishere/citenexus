// Package gate is the pinned CiteNexus faithfulness + relevance gates
// (SPEC-PORTS-v1 §4). It mirrors the Python reference
// citenexus.answer.verify: an extractive verifier that accepts a claim only
// when every answer token appears in the cited passage, plus a content-token
// relevance overlap test.
//
// The 44-word stopword set is the pinned SPEC-PORTS-v1 §10 list. It is EMBEDDED
// (a copy of conformance/stopwords.json, frozen per §10) so this module is
// self-contained and works when consumed as a Go dependency — a filesystem read
// of the shared conformance/ dir would not exist in the module cache.
package gate

import (
	_ "embed"
	"encoding/json"
	"sync"

	"github.com/muthuishere/citenexus/golang/tokenize"
)

//go:embed stopwords.json
var stopwordsJSON []byte

var (
	stopwordsOnce sync.Once
	stopwords     map[string]struct{}
)

// loadStopwords parses and caches the pinned 44-word stopword set from the
// embedded copy.
func loadStopwords() map[string]struct{} {
	stopwordsOnce.Do(func() {
		var words []string
		if err := json.Unmarshal(stopwordsJSON, &words); err != nil {
			panic("gate: unmarshal stopwords.json: " + err.Error())
		}
		set := make(map[string]struct{}, len(words))
		for _, w := range words {
			set[w] = struct{}{}
		}
		stopwords = set
	})
	return stopwords
}

// ContentTokens returns the meaning-bearing token set: tokenize(text) minus the
// pinned stopword set. Used by the relevance gate.
func ContentTokens(text string) map[string]struct{} {
	stop := loadStopwords()
	out := make(map[string]struct{})
	for _, tok := range tokenize.Tokenize(text) {
		if _, isStop := stop[tok]; isStop {
			continue
		}
		out[tok] = struct{}{}
	}
	return out
}

// HasRelevanceOverlap is true when question and passage share at least one
// content token.
func HasRelevanceOverlap(question, passage string) bool {
	q := ContentTokens(question)
	p := ContentTokens(passage)
	for tok := range q {
		if _, ok := p[tok]; ok {
			return true
		}
	}
	return false
}

// IsSupported is true when the answer has at least one token and every answer
// token (stopwords included) appears in the cited passage.
func IsSupported(answer, passage string) bool {
	answerToks := tokenize.Tokenize(answer)
	if len(answerToks) == 0 {
		return false
	}
	passageSet := make(map[string]struct{})
	for _, tok := range tokenize.Tokenize(passage) {
		passageSet[tok] = struct{}{}
	}
	for _, tok := range answerToks {
		if _, ok := passageSet[tok]; !ok {
			return false
		}
	}
	return true
}
