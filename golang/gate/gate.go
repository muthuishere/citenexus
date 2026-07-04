// Package gate is the pinned CiteNexus faithfulness + relevance gates
// (SPEC-PORTS-v1 §4). It mirrors the Python reference
// citenexus.answer.verify: an extractive verifier that accepts a claim only
// when every answer token appears in the cited passage, plus a content-token
// relevance overlap test.
//
// The 44-word stopword set is loaded from the pinned conformance/stopwords.json
// (SPEC-PORTS-v1 §10), never hardcoded, so every port shares one list.
package gate

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"sync"

	"github.com/muthuishere/citenexus/golang/tokenize"
)

var (
	stopwordsOnce sync.Once
	stopwords     map[string]struct{}
)

// stopwordsPath resolves conformance/stopwords.json relative to THIS source
// file so the pinned list is found from any working directory.
func stopwordsPath() string {
	_, self, _, _ := runtime.Caller(0)
	// self = <repo>/ports/go/gate/gate.go → up 3 to <repo>.
	repo := filepath.Join(filepath.Dir(self), "..", "..")
	return filepath.Join(repo, "conformance", "stopwords.json")
}

// loadStopwords reads and caches the pinned 44-word stopword set.
func loadStopwords() map[string]struct{} {
	stopwordsOnce.Do(func() {
		raw, err := os.ReadFile(stopwordsPath())
		if err != nil {
			panic("gate: read stopwords.json: " + err.Error())
		}
		var words []string
		if err := json.Unmarshal(raw, &words); err != nil {
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
