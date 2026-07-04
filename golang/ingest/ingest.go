//go:build citenexus_ffi

// Package ingest is the OPT-IN Go ingest orchestrator: it wires the shared Rust
// extractor and Lance store (via the cgo binding in golang/core) to the pure Go
// chunker, with the embedding model injected by the caller. It is behind the
// `citenexus_ffi` build tag for the same reason golang/core is — the pure port
// and CI stay clean and need no native library.
//
// Flow (SPEC-PORTS-v1 ingest): core.Extract → parse blocks → chunk each block
// with the pinned chunker → embed each chunk via the injected Embedder → build
// Evidence-Unit rows → upsert into the Lance store.
package ingest

import (
	"encoding/json"
	"fmt"

	"github.com/muthuishere/citenexus/golang/chunker"
	"github.com/muthuishere/citenexus/golang/core"
)

// Embedder turns chunk text into a dense vector. It is injected so the core owns
// orchestration and the model stays an endpoint (CLAUDE.md: no bundled models).
type Embedder interface {
	Embed(text string) []float64
}

// extractedDoc is the slice of the Rust ExtractedDoc JSON that ingest consumes.
type extractedDoc struct {
	Error      string `json:"error"`
	DocumentID string `json:"document_id"`
	Blocks     []struct {
		Order         int      `json:"order"`
		Kind          string   `json:"kind"`
		Text          string   `json:"text"`
		StructurePath []string `json:"structure_path"`
	} `json:"blocks"`
}

// Row is one Evidence-Unit row as upserted into the Lance store.
type Row struct {
	EuID       string    `json:"eu_id"`
	DocumentID string    `json:"document_id"`
	BlockOrder int       `json:"block_order"`
	ChunkIndex int       `json:"chunk_index"`
	Text       string    `json:"text"`
	Vector     []float64 `json:"vector"`
}

// Ingest extracts data as sourceType, chunks and embeds each block, and upserts
// the resulting Evidence-Unit rows into store. It returns the rows written.
func Ingest(store *core.Store, data []byte, sourceType, documentID string, embedder Embedder) ([]Row, error) {
	raw := core.Extract(data, sourceType, documentID)

	var doc extractedDoc
	if err := json.Unmarshal([]byte(raw), &doc); err != nil {
		return nil, fmt.Errorf("ingest: extract output not JSON: %w\n%s", err, raw)
	}
	if doc.Error != "" {
		return nil, fmt.Errorf("ingest: extract failed: %s", doc.Error)
	}

	var rows []Row
	for _, block := range doc.Blocks {
		chunks := chunker.ChunkText(block.Text, chunker.DefaultMaxTokens, chunker.DefaultOverlap)
		for ci, chunk := range chunks {
			vec := embedder.Embed(chunk)
			rows = append(rows, Row{
				EuID:       fmt.Sprintf("%s:b%d:c%d", documentID, block.Order, ci),
				DocumentID: documentID,
				BlockOrder: block.Order,
				ChunkIndex: ci,
				Text:       chunk,
				Vector:     vec,
			})
		}
	}

	if len(rows) == 0 {
		return rows, nil
	}

	rowsJSON, err := json.Marshal(rows)
	if err != nil {
		return nil, fmt.Errorf("ingest: marshal rows: %w", err)
	}
	if out := store.Upsert(string(rowsJSON)); isError(out) {
		return nil, fmt.Errorf("ingest: store upsert failed: %s", out)
	}
	return rows, nil
}

// isError reports whether a C ABI JSON reply carries an "error" key.
func isError(jsonReply string) bool {
	var probe struct {
		Error *string `json:"error"`
	}
	if err := json.Unmarshal([]byte(jsonReply), &probe); err != nil {
		return true
	}
	return probe.Error != nil
}
