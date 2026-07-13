//go:build !citenexus_ffi

package main

import (
	"fmt"
	"strings"

	"github.com/muthuishere/citenexus/golang/cli/engine"
)

// pureExtractor is the default-build extractor: it handles text-like artifacts
// natively (no Rust core, no cgo) by splitting on blank lines into blocks. Binary
// formats (pdf/docx/pptx/xlsx/image) require the citenexus_ffi build, which
// static-links the shared Rust engine.
type pureExtractor struct{}

// newExtractor is build-tag provided; the default build returns the pure one.
func newExtractor() engine.Extractor { return pureExtractor{} }

var pureTextTypes = map[string]bool{
	"plain": true, "txt": true, "md": true, "markdown": true,
	"csv": true, "text": true, "log": true, "json": true,
}

func (pureExtractor) Extract(data []byte, sourceType, documentID string) ([]engine.Block, error) {
	if !pureTextTypes[strings.ToLower(sourceType)] {
		return nil, fmt.Errorf("extract: %q needs the citenexus_ffi build (Rust core); the default build handles text formats only", sourceType)
	}
	text := string(data)
	// Split on blank-line boundaries into blocks; a single block otherwise.
	parts := strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n\n")
	var blocks []engine.Block
	order := 0
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		blocks = append(blocks, engine.Block{Order: order, Kind: "text", Text: p})
		order++
	}
	if len(blocks) == 0 {
		blocks = append(blocks, engine.Block{Order: 0, Kind: "text", Text: strings.TrimSpace(text)})
	}
	return blocks, nil
}
