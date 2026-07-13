//go:build citenexus_ffi

package main

import (
	"encoding/json"
	"fmt"

	"github.com/muthuishere/citenexus/golang/cli/engine"
	"github.com/muthuishere/citenexus/golang/core"
)

// coreExtractor routes extraction through the shared Rust engine (citenexus-core)
// via the cgo binding in golang/core — the full-format path (pdf, docx, pptx,
// xlsx, html, image+OCR, …), byte-identical with the Python reference. Built only
// under the citenexus_ffi tag; the CLI's production build static-links the core.
type coreExtractor struct{}

// newExtractor is build-tag provided; the citenexus_ffi build returns the core one.
func newExtractor() engine.Extractor { return coreExtractor{} }

// extractedDoc is the slice of the Rust ExtractedDoc JSON we consume (mirrors
// golang/ingest.extractedDoc).
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

func (coreExtractor) Extract(data []byte, sourceType, documentID string) ([]engine.Block, error) {
	raw := core.Extract(data, sourceType, documentID)
	var doc extractedDoc
	if err := json.Unmarshal([]byte(raw), &doc); err != nil {
		return nil, fmt.Errorf("extract: core output not JSON: %w", err)
	}
	if doc.Error != "" {
		return nil, fmt.Errorf("extract: %s", doc.Error)
	}
	blocks := make([]engine.Block, len(doc.Blocks))
	for i, b := range doc.Blocks {
		blocks[i] = engine.Block{Order: b.Order, Kind: b.Kind, Text: b.Text, StructurePath: b.StructurePath}
	}
	return blocks, nil
}
