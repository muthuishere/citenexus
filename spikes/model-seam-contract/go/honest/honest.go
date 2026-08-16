// This package DOES NOT COMPILE, on purpose. It is the second half of the
// proof for ADR-0014's claim 3: an embedder that reports failure honestly is
// *structurally* rejected by the seam, so a provider cannot even opt in.
//
// Run: go build ./spikes/model-seam-contract/go/honest   (expect a type error)
package honest

// Copy of golang/ingest/ingest.go:22-24.
type Embedder interface {
	Embed(text string) []float64
}

// What every provider actually wants to write.
type HonestEmbedder struct{}

func (HonestEmbedder) Embed(text string) ([]float64, error) { return nil, nil }

// The assertion the compiler refuses.
var _ Embedder = HonestEmbedder{}
