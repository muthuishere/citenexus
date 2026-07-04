// Package fakes holds the deterministic, offline test doubles that make the
// CiteNexus cite-or-abstain flow provable without any model server
// (SPEC-PORTS-v1 §0/§4). They mirror the Python reference
// citenexus.testing.fakes: a hash-bucketed embedding, an evidence-echoing LLM,
// and a cosine over already-normalized vectors.
package fakes

import (
	"crypto/sha1"
	"math"

	"github.com/muthuishere/citenexus/golang/tokenize"
)

// Dim is the fixed embedding dimensionality (§4).
const Dim = 64

// FakeEmbedding is a hash-bucketed bag-of-tokens embedder: each pinned token is
// hashed into one of Dim buckets and increments it, then the vector is
// L2-normalized. Deterministic and offline — the property that makes the
// guarantee testable.
type FakeEmbedding struct{}

// Embed maps text to a unit vector of length Dim. For each token produced by the
// pinned tokenizer, bucket = sha1(utf8(token)) mod Dim (the full 160-bit digest
// mod 64 collapses to the low 6 bits of its least-significant byte). The result
// is L2-normalized; an all-zero vector (no tokens) is left as zeros.
func (FakeEmbedding) Embed(text string) []float64 {
	vec := make([]float64, Dim)
	for _, tok := range tokenize.Tokenize(text) {
		sum := sha1.Sum([]byte(tok))
		idx := int(sum[len(sum)-1] & 0x3F) // digest mod 64 == low 6 bits.
		vec[idx] += 1.0
	}
	var norm float64
	for _, v := range vec {
		norm += v * v
	}
	norm = math.Sqrt(norm)
	if norm != 0 {
		for i := range vec {
			vec[i] /= norm
		}
	}
	return vec
}

// FakeLLM is an evidence-echoing generator: it returns the cited passage
// verbatim, so the faithfulness gate is exercised honestly rather than bypassed.
type FakeLLM struct{}

// Answer returns the passage unchanged, ignoring the question.
func (FakeLLM) Answer(question, passage string) string { return passage }

// Cosine is the dot product of a and b. FakeEmbedding vectors are already
// L2-normalized, so the dot product is their cosine similarity.
func Cosine(a, b []float64) float64 {
	var dot float64
	for i := range a {
		dot += a[i] * b[i]
	}
	return dot
}
