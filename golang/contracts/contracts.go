// Package contracts is the Go port's published model seam — the single place a
// provider author looks (ADR-0014 R1 + R4).
//
// CiteNexus bundles no models. What it owes anyone who wants to supply one is an
// interface they can implement without reading our call sites. This package is
// that interface, and it deliberately **imports nothing** — not even another
// CiteNexus package — so implementing a contract costs a provider author one
// file's worth of reading and no dependency they did not already have.
//
// # Two contracts, not five
//
// The Python reference publishes five (embedding, generation, completion,
// vision, reranking). The Go port publishes the TWO it actually consumes:
//
//	EmbeddingProvider   Embed(texts)                       -> ([][]float64, error)
//	GeneratorProvider   Answer(question, passage, langISO)  -> (string, error)
//
// Completion, vision and reranking are absent ON PURPOSE. The Go port has no
// deep-ask decision loop (golang/result/result.go says so outright: "Deep-ask is
// Python-only today"), no conditional-vision path, and no rerank symbol
// anywhere — not even a candidate type the contract could be written in terms
// of. A published contract asserts that implementing it makes the library use
// your provider; publishing one for a seam with no call site would make that
// assertion falsely. They are withheld until a port grows the consumer, not
// refused on principle: their shape is already settled by Python, so each is a
// one-file addition the day there is something to call it.
//
// # Why Embed and not EmbedMany
//
// Python had to name the batch method embed_many because in Python a str IS a
// Sequence[str], so a method spelled `embed` could not be told apart from the
// single-text shape by isinstance or by a type checker. That hazard is a
// property of Python's Sequence protocol and does NOT exist in Go: string and
// []string are unrelated types, the compiler rejects the wrong one at the
// assignment, and a type assertion to EmbeddingProvider cannot match the
// single-text shape. (contracts_test.go proves this rather than asserting it.)
//
// So Go uses the natural name — which is also, not by coincidence, the name the
// shipped client golang/models.OpenAIEmbedding already has. R4 asks for
// identical semantics across ports, not identical identifiers.
//
// # Failure is an error, never a sentinel
//
// Every method returns (value, error). A zero vector is not an error value: it
// is a valid embedding of something, and once written it is indistinguishable
// from a document that genuinely embeds near the origin, so retrieval scores it
// 0.0000 with no error and no flag (ADR-0014 R2). An empty string is an answer,
// not a failure. A (nil, nil) return is the same silent poison. A provider that
// did not do the work MUST say so through the error.
//
// # Nothing here mentions a transport
//
// Base URLs, headers and transports are CONSTRUCTOR parameters of the HTTP
// clients in golang/models, never contract methods, so a provider that never
// opens a socket satisfies every contract in this package (ADR-0014 R3).
package contracts

import (
	"errors"
	"fmt"
	"math"
)

// Vector is one dense embedding. Named so the contracts read as intent rather
// than as plumbing; it is a plain alias, so [][]float64 and []Vector are the
// same type and no caller is forced to convert.
type Vector = []float64

// EmbeddingProvider turns texts into dense vectors. **Batch is the primitive**
// (ADR-0014 R1): a single text is a batch of one, not a second method, because
// batching is where the throughput is and a seam that hides it behind an
// optional second method is a seam nobody uses.
//
// Implementations MUST return exactly one vector per input text, in input
// order, and MUST return a non-nil error rather than a placeholder vector when
// the model did not actually embed the text.
type EmbeddingProvider interface {
	Embed(texts []string) ([][]float64, error)
}

// GeneratorProvider produces a grounded answer from one already-selected
// passage, in the requested ISO language.
//
// The provider is handed the passage the library chose. It does not retrieve,
// it does not choose evidence, and it is NOT trusted: whatever it returns goes
// through the faithfulness gate before it can become an answer. The best
// possible generator is therefore an extractive one — quote the passage.
//
// Implementations MUST return a non-nil error rather than an empty string when
// they could not generate.
type GeneratorProvider interface {
	Answer(question, passage, answerLanguage string) (string, error)
}

// SingleTextEmbedder is the DEPRECATED one-text-at-a-time embedding shape.
//
// Published so the ingest seam (golang/ingest.Embedder) is an ALIAS of one
// definition rather than a second declaration that can drift from it. Still
// fully supported — EmbedTexts falls back to it — but a new provider should
// implement EmbeddingProvider instead: this shape cannot batch, and one request
// per Evidence Unit does not survive a real corpus.
type SingleTextEmbedder interface {
	Embed(text string) ([]float64, error)
}

// ErrNotAnEmbedder is returned by EmbedTexts for a value that satisfies neither
// embedding contract. Go has no union type, so the dispatch helper takes `any`
// and must be able to refuse — refusing loudly beats embedding nothing quietly.
var ErrNotAnEmbedder = errors.New(
	"contracts: value implements neither EmbeddingProvider (Embed([]string) ([][]float64, error)) " +
		"nor SingleTextEmbedder (Embed(string) ([]float64, error))")

// EmbedTexts embeds texts, preferring the batch contract.
//
// This is the ONE place the Go port decides how to talk to an embedder — the
// twin of Python's contracts.embed_texts, and the reason batching is not a
// capability discovered by reflection. Passing `any` is the price of Go having
// no union type; the type switch below is the whole of the decision.
//
// An empty input embeds nothing and calls no model.
func EmbedTexts(embedder any, texts []string) ([][]float64, error) {
	if len(texts) == 0 {
		return nil, nil
	}
	switch e := embedder.(type) {
	case EmbeddingProvider:
		vecs, err := e.Embed(texts)
		if err != nil {
			return nil, err
		}
		if len(vecs) != len(texts) {
			return nil, fmt.Errorf(
				"contracts: embedder returned %d vectors for %d texts; the contract is one "+
					"vector per input text, in input order", len(vecs), len(texts))
		}
		return vecs, nil
	case SingleTextEmbedder:
		out := make([][]float64, len(texts))
		for i, text := range texts {
			vec, err := e.Embed(text)
			if err != nil {
				return nil, err
			}
			out[i] = vec
		}
		return out, nil
	default:
		return nil, ErrNotAnEmbedder
	}
}

// EmbedOne embeds a single text — a batch of one under the contract.
func EmbedOne(embedder any, text string) ([]float64, error) {
	vecs, err := EmbedTexts(embedder, []string{text})
	if err != nil {
		return nil, err
	}
	if len(vecs) == 0 {
		return nil, fmt.Errorf("contracts: embedder returned nothing for a single input")
	}
	return vecs[0], nil
}

// SingleFrom adapts a batch provider to the deprecated single-text seam, so a
// provider written against the contract plugs straight into ingest without the
// author writing glue. It is the inverse of EmbedTexts's fallback.
func SingleFrom(provider EmbeddingProvider) SingleTextEmbedder {
	return singleFrom{provider}
}

type singleFrom struct{ provider EmbeddingProvider }

func (s singleFrom) Embed(text string) ([]float64, error) {
	return EmbedOne(s.provider, text)
}

// IsZeroVector reports whether vec carries no signal at all. Twin of the Python
// reference citenexus.testing.fakes.is_zero_vector.
func IsZeroVector(vec []float64) bool {
	for _, v := range vec {
		if v != 0 {
			return false
		}
	}
	return true
}

// CheckVector rejects a vector that must never be indexed or scored. It is the
// belt to the contracts' error-return braces: even a seam that CAN report
// failure does not stop a provider that returns a degenerate vector while
// reporting success.
//
// label names the thing being embedded (an eu_id on the write path, a document
// id or "question" on the ask path). dim is the dimensionality already
// established by this run — 0 for the first vector, which defines it.
//
// Four rejections, in THIS order — the order is part of the contract, not an
// implementation detail. A vector can fail more than one rule at once, and three
// ports that disagree about which error to report are three ports that disagree
// about the contract. It is pinned by conformance/cases/vector_validation.json,
// which python/tests/conformance/test_vector_validation_vectors.py,
// contracts/vector_validation_test.go and js/src/contracts.vector.test.ts all
// replay.
//
//   - empty/nil — no vector at all; unguarded it surfaces later as a dimension
//     mismatch deep inside the store, misattributed to storage rather than the model.
//   - wrong dimension — one run's vectors must be mutually comparable.
//   - non-finite — NaN and ±Inf. Every comparison with NaN is false, so it does
//     not merely score badly: it makes the RANKING depend on the sort algorithm
//     rather than on the data, and the corpus ranks differently on different runs
//     with nothing reporting a fault. This rejection was MISSING here while JS
//     had it (js/src/contracts.ts), so the two "byte-identical" ports disagreed
//     about what a valid vector is. Added to close that divergence.
//   - all zeros — the silent poison ADR-0014 names. Cosine against it does not
//     fail, it just ranks meaninglessly.
//
// Go needs no "not a vector at all" rejection: []float64 makes it
// unrepresentable. Python and JS, both dynamically typed, carry one — which is
// why the conformance vector keeps those cases in their own bucket.
func CheckVector(label string, vec []float64, dim int) error {
	if len(vec) == 0 {
		return fmt.Errorf("embedder returned an empty vector for %s", label)
	}
	if dim > 0 && len(vec) != dim {
		return fmt.Errorf(
			"embedder returned a %d-dim vector for %s; this run is %d-dim", len(vec), label, dim)
	}
	for _, v := range vec {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return fmt.Errorf("embedder returned a non-finite vector for %s", label)
		}
	}
	if IsZeroVector(vec) {
		return fmt.Errorf(
			"embedder returned the zero vector for %s — it carries no signal and would rank "+
				"meaninglessly against every query", label)
	}
	return nil
}
