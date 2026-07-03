// Package lang is the pinned CiteNexus answer-language fallback chain
// (SPEC-PORTS-v1 §4, §11a). It mirrors citenexus.lang.fallback.resolve_answer_language.
package lang

// Detection is the query language-detection result feeding the chain.
type Detection struct {
	Language   string  `json:"language"`
	Confidence float64 `json:"confidence"`
	IsReliable bool    `json:"is_reliable"`
}

// ResolveAnswerLanguage picks the answer language by the §11a ordered chain:
//  1. reliable detection of the query language;
//  2. explicit answerLanguage override;
//  3. established conversationLanguage;
//  4. dominant language among languagesInEvidence (ties → first-seen, stable);
//  5. configured defaultAnswerLanguage.
func ResolveAnswerLanguage(
	detection *Detection,
	answerLanguage string,
	conversationLanguage string,
	languagesInEvidence []string,
	defaultAnswerLanguage string,
) string {
	if detection != nil && detection.IsReliable {
		return detection.Language
	}
	if answerLanguage != "" {
		return answerLanguage
	}
	if conversationLanguage != "" {
		return conversationLanguage
	}
	if len(languagesInEvidence) > 0 {
		return dominant(languagesInEvidence)
	}
	return defaultAnswerLanguage
}

// dominant returns the most frequent language, resolving ties to the first-seen
// (insertion order) — matching Python collections.Counter.most_common(1).
func dominant(langs []string) string {
	counts := make(map[string]int)
	var order []string
	for _, l := range langs {
		if _, seen := counts[l]; !seen {
			order = append(order, l)
		}
		counts[l]++
	}
	best := order[0]
	for _, l := range order {
		if counts[l] > counts[best] {
			best = l
		}
	}
	return best
}
