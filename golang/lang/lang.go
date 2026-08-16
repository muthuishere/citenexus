// Package lang is the pinned CiteNexus answer-language fallback chain
// (SPEC-PORTS-v1 §4, §11a). It mirrors citenexus.lang.fallback.resolve_answer_language.
//
// BREAKING (2026-08-16): the chain no longer derives the answer language from
// the retrieved evidence, and an explicit answerLanguage now OUTRANKS a reliable
// detection. The old fourth rung was a corpus-shaped signal wearing §11's name:
// measured on examples/multilingual/, it stamped 15 of 22 English questions with
// a Telugu or Tamil answer language purely because the retrieved passages were
// in those languages. The rule is now explicit-first, with a dumb default.
package lang

// AutoAnswerLanguage is the one value of answerLanguage that is not a language:
// "detect it from my question". Resolution of the sentinel (running a detector
// over the question) happens a layer above this pinned function; here it merely
// does not count as an explicit request, and is never returned.
const AutoAnswerLanguage = "auto"

// Detection is the QUESTION language-detection result feeding the chain.
type Detection struct {
	Language   string  `json:"language"`
	Confidence float64 `json:"confidence"`
	IsReliable bool    `json:"is_reliable"`
}

// ResolveAnswerLanguage picks the answer language by the §11a ordered chain:
//  1. explicit answerLanguage — the caller's word outranks the classifier;
//  2. a reliable detection of the QUESTION;
//  3. established conversationLanguage;
//  4. configured defaultAnswerLanguage (the dumb default).
//
// languagesInEvidence is still accepted and is IGNORED. It stays in the
// signature so the Python / Go / JS / Rust ports and the conformance vectors
// keep an identical argument list — the port diff is a verdict diff, not an API
// diff. Evidence languages remain an observation to REPORT, never an input.
func ResolveAnswerLanguage(
	detection *Detection,
	answerLanguage string,
	conversationLanguage string,
	languagesInEvidence []string,
	defaultAnswerLanguage string,
) string {
	_ = languagesInEvidence // accepted for signature stability; never read.
	if answerLanguage != "" && answerLanguage != AutoAnswerLanguage {
		return answerLanguage
	}
	if detection != nil && detection.IsReliable {
		return detection.Language
	}
	if conversationLanguage != "" {
		return conversationLanguage
	}
	return defaultAnswerLanguage
}
