package chunker

import (
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// The chunker is proven against the shared fixture — every case must match the
// Python reference exactly (SPEC-PORTS-v1 §4/§10). Byte-identical output over ALL
// cases, no leniency, no skips.
func TestChunkerConformance(t *testing.T) {
	var cases []struct {
		Text      string   `json:"text"`
		MaxTokens int      `json:"max_tokens"`
		Overlap   int      `json:"overlap"`
		Chunks    []string `json:"chunks"`
	}
	conform.Case(t, "chunker.json", &cases)

	if len(cases) == 0 {
		t.Fatal("no chunker cases loaded")
	}
	for i, c := range cases {
		got := ChunkText(c.Text, c.MaxTokens, c.Overlap)
		want := c.Chunks
		if want == nil {
			want = []string{}
		}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("case %d: ChunkText(%q, max=%d, overlap=%d) =\n  %#v\nwant\n  %#v",
				i, c.Text, c.MaxTokens, c.Overlap, got, want)
		}
	}
}
