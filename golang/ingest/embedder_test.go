// Tests for the model seam and the write-path vector guard. No build tag: these
// run in the default `go test ./...` with no native library, which is the point
// — the guarantee "a degenerate vector never becomes a row" is provable offline.

package ingest

import (
	"errors"
	"strings"
	"testing"
)

// honestEmbedder is what a real provider looks like: it embeds, or it says why
// it could not. Before ADR-0014 R2 this type was STRUCTURALLY REJECTED by the
// seam (`have Embed(string) ([]float64, error) / want Embed(string) []float64`),
// which is why no real model client could ever be injected into ingest.
type honestEmbedder struct {
	calls  int
	failOn int // 1-based call index that fails; 0 = never fail.
}

var errModelTimeout = errors.New("model call timed out after 30s")

func (e *honestEmbedder) Embed(text string) ([]float64, error) {
	e.calls++
	if e.failOn != 0 && e.calls == e.failOn {
		return nil, errModelTimeout
	}
	return []float64{1, 0, 0, float64(len(text))}, nil
}

// A failing embedder must be able to satisfy the seam at all — compile-time.
var _ Embedder = (*honestEmbedder)(nil)

// And a bare function of the same shape must plug in, so the OpenAI client's
// existing EmbedQuery(string) ([]float64, error) needs no adapter type.
var _ Embedder = EmbedderFunc(func(string) ([]float64, error) { return nil, nil })

func TestEmbedderFuncForwardsBothResults(t *testing.T) {
	vec, err := EmbedderFunc(func(text string) ([]float64, error) {
		return []float64{float64(len(text))}, nil
	}).Embed("abcd")
	if err != nil || len(vec) != 1 || vec[0] != 4 {
		t.Fatalf("EmbedderFunc did not forward: vec=%v err=%v", vec, err)
	}

	if _, err := EmbedderFunc(func(string) ([]float64, error) {
		return nil, errModelTimeout
	}).Embed("x"); !errors.Is(err, errModelTimeout) {
		t.Fatalf("EmbedderFunc swallowed the error: %v", err)
	}
}

func TestHonestEmbedderReportsFailure(t *testing.T) {
	emb := &honestEmbedder{failOn: 2}
	if _, err := emb.Embed("first"); err != nil {
		t.Fatalf("first call should succeed: %v", err)
	}
	_, err := emb.Embed("the employee may not disclose the defect")
	if !errors.Is(err, errModelTimeout) {
		t.Fatalf("the seam must let the model say it failed; got %v", err)
	}
}

// The regression this whole change exists for: the zero vector ADR-0014 names.
// Before the guard, a model that timed out returned make([]float64, dim) and
// ingest indexed it — the row scored cosine 0.0000 against every query, with no
// error and no flag, indistinguishable from a document that genuinely embeds far
// away. The evidence was silently missing from the corpus.
func TestCheckVectorRejectsTheZeroVector(t *testing.T) {
	err := checkVector("doc-1:b0:c1", []float64{0, 0, 0, 0}, 4)
	if err == nil {
		t.Fatal("the zero vector was accepted onto the write path")
	}
	if !strings.Contains(err.Error(), "zero vector") {
		t.Fatalf("error should name the zero vector: %v", err)
	}
}

func TestCheckVectorRejectsEmptyAndWrongDimension(t *testing.T) {
	if err := checkVector("eu", nil, 0); err == nil {
		t.Fatal("a nil vector was accepted")
	}
	if err := checkVector("eu", []float64{}, 0); err == nil {
		t.Fatal("an empty vector was accepted")
	}
	if err := checkVector("eu", []float64{1, 2}, 4); err == nil {
		t.Fatal("a 2-dim vector was accepted into a 4-dim run")
	}
}

func TestCheckVectorAcceptsARealVector(t *testing.T) {
	// dim 0 = this vector defines the run's dimensionality.
	if err := checkVector("eu", []float64{0, 0, 0.5, 0}, 0); err != nil {
		t.Fatalf("a real (sparse but non-zero) vector was rejected: %v", err)
	}
	if err := checkVector("eu", []float64{0, 0, 0.5, 0}, 4); err != nil {
		t.Fatalf("a matching-dimension vector was rejected: %v", err)
	}
}

func TestIsZeroVector(t *testing.T) {
	for _, c := range []struct {
		vec  []float64
		want bool
	}{
		{[]float64{0, 0, 0}, true},
		{[]float64{}, true},
		{[]float64{0, 0, -0.0}, true},
		{[]float64{0, 1e-12, 0}, false},
		{[]float64{-1, 0, 0}, false},
	} {
		if got := isZeroVector(c.vec); got != c.want {
			t.Fatalf("isZeroVector(%v) = %v, want %v", c.vec, got, c.want)
		}
	}
}
