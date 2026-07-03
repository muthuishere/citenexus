package euid

import (
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus-go/internal/conform"
)

// The Evidence-Unit id + block builder is proven against the shared fixture:
// every case's block-builder and chunked-builder eu_id lists must match the
// Python reference exactly, and the checksum example must reproduce byte-for-byte.
func TestEUIDConformance(t *testing.T) {
	var fixture struct {
		Cases []struct {
			Name           string   `json:"name"`
			DocumentID     string   `json:"document_id"`
			Blocks         []Block  `json:"blocks"`
			ChunkMaxTokens int      `json:"chunk_max_tokens"`
			ChunkOverlap   int      `json:"chunk_overlap"`
			BlockEUIDs     []string `json:"block_builder_eu_ids"`
			ChunkedEUIDs   []string `json:"chunked_builder_eu_ids"`
		} `json:"cases"`
		ChecksumExample struct {
			RawUTF8 string `json:"raw_utf8"`
			SHA256  string `json:"sha256"`
		} `json:"checksum_example"`
	}
	conform.Case(t, "eu_ids.json", &fixture)

	if len(fixture.Cases) == 0 {
		t.Fatal("no eu_ids cases loaded")
	}

	for _, c := range fixture.Cases {
		gotBlock := BlockBuilderEUIDs(c.DocumentID, c.Blocks)
		wantBlock := c.BlockEUIDs
		if wantBlock == nil {
			wantBlock = []string{}
		}
		if !reflect.DeepEqual(gotBlock, wantBlock) {
			t.Errorf("%s: BlockBuilderEUIDs = %v, want %v", c.Name, gotBlock, wantBlock)
		}

		gotChunked := ChunkedBuilderEUIDs(c.DocumentID, c.Blocks, c.ChunkMaxTokens, c.ChunkOverlap)
		wantChunked := c.ChunkedEUIDs
		if wantChunked == nil {
			wantChunked = []string{}
		}
		if !reflect.DeepEqual(gotChunked, wantChunked) {
			t.Errorf("%s: ChunkedBuilderEUIDs = %v, want %v", c.Name, gotChunked, wantChunked)
		}
	}

	if fixture.ChecksumExample.SHA256 != "" {
		got := Checksum(fixture.ChecksumExample.RawUTF8)
		if got != fixture.ChecksumExample.SHA256 {
			t.Errorf("Checksum(%q) = %s, want %s", fixture.ChecksumExample.RawUTF8, got, fixture.ChecksumExample.SHA256)
		}
	}
}
