// The model seam and the write-path vector guard. Deliberately NOT behind the
// `citenexus_ffi` build tag: the contract a provider has to satisfy, and the
// check that keeps a degenerate vector out of the corpus, are pure Go. Keeping
// them here means both are compiled and unit-tested in the default build, with
// no native library and no C toolchain (ADR-0014 R2).

package ingest

import "fmt"

// Embedder turns chunk text into a dense vector, or reports why it could not.
// It is injected so the core owns orchestration and CiteNexus bundles no models.
//
// The error return is the contract, not decoration (ADR-0014 R2): a model that
// times out, refuses, rate-limits or runs out of memory must be able to SAY so.
// Without it the only things an implementation can return are a zero vector, a
// nil slice, or a panic — and a zero vector is not an error value. It is a valid
// embedding of something, so once written it is indistinguishable from a
// document that genuinely embeds near the origin, and retrieval scores it 0.0000
// with no error and no flag. That is a wrong the library cannot see.
//
// An implementation MUST return a non-nil error rather than a placeholder vector
// whenever it did not actually embed the text.
type Embedder interface {
	Embed(text string) ([]float64, error)
}

// EmbedderFunc adapts a plain function to Embedder (the http.HandlerFunc
// pattern), so a client that already has the right shape plugs straight in:
//
//	client := models.NewOpenAIEmbedding(baseURL, model, transport)
//	rows, err := ingest.Ingest(store, data, "pdf", "doc-1", ingest.EmbedderFunc(client.EmbedQuery))
type EmbedderFunc func(text string) ([]float64, error)

// Embed calls f.
func (f EmbedderFunc) Embed(text string) ([]float64, error) { return f(text) }

// isZeroVector reports whether vec carries no signal at all. Twin of the Python
// reference citenexus.testing.fakes.is_zero_vector, promoted here from test-only
// helper to write-path guard.
func isZeroVector(vec []float64) bool {
	for _, v := range vec {
		if v != 0 {
			return false
		}
	}
	return true
}

// checkVector rejects a vector that must never become an Evidence-Unit row. It
// is the belt to the Embedder error return's braces: even with a seam that CAN
// report failure, a provider that returns a degenerate vector without erroring
// must not poison the corpus.
//
// dim is the dimensionality already established by this ingest run (0 for the
// first vector, which defines it). Three rejections:
//
//   - empty/nil — no vector at all; unguarded it becomes a dimension mismatch
//     deep inside the store, misattributed to storage rather than to the model.
//   - wrong dimension — the run's vectors must be mutually comparable.
//   - all zeros — the silent poison ADR-0014 names. Cosine against it does not
//     raise, it just ranks meaninglessly.
func checkVector(euID string, vec []float64, dim int) error {
	if len(vec) == 0 {
		return fmt.Errorf("ingest: embedder returned an empty vector for %s", euID)
	}
	if dim > 0 && len(vec) != dim {
		return fmt.Errorf(
			"ingest: embedder returned a %d-dim vector for %s; this run is %d-dim",
			len(vec), euID, dim,
		)
	}
	if isZeroVector(vec) {
		return fmt.Errorf(
			"ingest: embedder returned the zero vector for %s — it carries no signal and "+
				"would rank meaninglessly against every query", euID,
		)
	}
	return nil
}
