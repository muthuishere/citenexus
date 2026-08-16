// Spike: prove ADR-0014's claim that the Go embedder seam cannot report failure.
//
// The Embedder interface and the embed loop below are copied VERBATIM from
// golang/ingest/ingest.go (interface at :22-24, loop at :64-77) with only the
// Rust-FFI store and chunker replaced by in-memory stubs, because golang/ingest
// is behind the `citenexus_ffi` build tag and needs a native library that is not
// built in this checkout. Nothing about the seam's shape is changed.
//
// Run: go run ./spikes/model-seam-contract/go
package main

import (
	"errors"
	"fmt"
	"math"
	"strings"
)

// ---- VERBATIM from golang/ingest/ingest.go:22-24 -------------------------

// Embedder turns chunk text into a dense vector. It is injected so the core owns
// orchestration and the model stays an endpoint (CLAUDE.md: no bundled models).
type Embedder interface {
	Embed(text string) []float64
}

// ---- VERBATIM row shape from golang/ingest/ingest.go:39-46 ---------------

type Row struct {
	EuID       string    `json:"eu_id"`
	DocumentID string    `json:"document_id"`
	BlockOrder int       `json:"block_order"`
	ChunkIndex int       `json:"chunk_index"`
	Text       string    `json:"text"`
	Vector     []float64 `json:"vector"`
}

// ---- stubs standing in for core.Store / chunker.ChunkText ----------------

type store struct{ rows []Row }

func (s *store) Upsert(rows []Row) { s.rows = append(s.rows, rows...) }

func chunkText(text string) []string { return strings.Split(text, "\n") }

// ---- VERBATIM embed loop from golang/ingest/ingest.go:63-79 --------------

func ingest(s *store, blocks []string, documentID string, embedder Embedder) ([]Row, error) {
	var rows []Row
	for order, block := range blocks {
		chunks := chunkText(block)
		for ci, chunk := range chunks {
			vec := embedder.Embed(chunk) // <-- no error can come back out of here
			rows = append(rows, Row{
				EuID:       fmt.Sprintf("%s:b%d:c%d", documentID, order, ci),
				DocumentID: documentID,
				BlockOrder: order,
				ChunkIndex: ci,
				Text:       chunk,
				Vector:     vec,
			})
		}
	}
	s.Upsert(rows)
	return rows, nil
}

// ---- the two embedders a real provider would write ----------------------

// goodEmbedder: a deterministic in-process "model".
type goodEmbedder struct{}

func (goodEmbedder) Embed(text string) []float64 {
	v := make([]float64, 4)
	for i, r := range text {
		v[i%4] += float64(r%17) / 17.0
	}
	return v
}

// timeoutEmbedder: the model timed out / refused / OOM'd on the SECOND chunk.
// The interface gives it nowhere to say so. Every real implementation of a
// no-error signature must return *some* slice; the only choices are a zero
// vector, a nil slice, or panic.
type timeoutEmbedder struct {
	calls int
	err   error // recorded, but structurally unreportable to the caller
}

func (e *timeoutEmbedder) Embed(text string) []float64 {
	e.calls++
	if e.calls == 2 {
		e.err = errors.New("model call timed out after 30s")
		return make([]float64, 4) // <-- the zero vector ADR-0014 names
	}
	return goodEmbedder{}.Embed(text)
}

// ---- retrieval: can it tell? --------------------------------------------

func cosine(a, b []float64) float64 {
	var dot, na, nb float64
	for i := range a {
		dot += a[i] * b[i]
		na += a[i] * a[i]
		nb += b[i] * b[i]
	}
	if na == 0 || nb == 0 {
		return 0 // a zero vector scores 0 against everything: a legal, silent "far away"
	}
	return dot / (math.Sqrt(na) * math.Sqrt(nb))
}

func main() {
	blocks := []string{
		"the employee may disclose the defect\nthe employee may not disclose the defect",
		"disclosure requires written consent",
	}

	fmt.Println("== CLAIM 3: Go Embed(text string) []float64 cannot report failure ==")

	var okStore store
	_, _ = ingest(&okStore, blocks, "doc-1", goodEmbedder{})

	var badStore store
	failing := &timeoutEmbedder{}
	rows, err := ingest(&badStore, blocks, "doc-1", failing)

	fmt.Printf("ingest() returned err = %v   <-- ingest saw NOTHING wrong\n", err)
	fmt.Printf("the embedder's real failure was: %v   <-- it died inside the seam\n", failing.err)
	fmt.Printf("rows written: %d (same as the healthy run: %d)\n", len(rows), len(okStore.rows))

	fmt.Println("\n-- what landed in the store --")
	for i, r := range badStore.rows {
		zero := true
		for _, x := range r.Vector {
			if x != 0 {
				zero = false
			}
		}
		mark := " "
		if zero {
			mark = "*"
		}
		fmt.Printf("%s row %d  eu_id=%-14s vector=%v  text=%q\n", mark, i, r.EuID, r.Vector, r.Text)
	}

	fmt.Println("\n-- can retrieval detect the poisoned row? --")
	q := goodEmbedder{}.Embed("may the employee disclose the defect")
	for i, r := range badStore.rows {
		fmt.Printf("  row %d  cosine=%.4f   (a schema-valid float64 score; no error, no flag)\n", i, cosine(q, r.Vector))
	}
	fmt.Println("  => the poisoned EU is simply 'not similar'. It is indistinguishable from")
	fmt.Println("     a document that genuinely embeds far from the query. The corpus is")
	fmt.Println("     silently missing evidence, and ask() will happily abstain or answer")
	fmt.Println("     from worse evidence with full confidence. VERDICT: claim 3 HOLDS.")

	fmt.Println("\n-- and nil is no better --")
	var nilStore store
	_, _ = ingest(&nilStore, blocks[:1], "doc-2", nilEmbedder{})
	fmt.Printf("  nil-returning embedder row vector = %v (len %d) -> a dimension-mismatch\n",
		nilStore.rows[0].Vector, len(nilStore.rows[0].Vector))
	fmt.Println("  crash DEEP inside the store, attributed to storage, not to the model.")
}

type nilEmbedder struct{}

func (nilEmbedder) Embed(text string) []float64 { return nil }
