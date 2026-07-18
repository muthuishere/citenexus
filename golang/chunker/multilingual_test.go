package chunker

import (
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// The multilingual anti-drift corpus (ADR-0006) run through the chunker: word
// counting is Unicode-whitespace aware (ideographic space U+3000 splits), and
// paragraph/line boundaries must agree byte-for-byte with the Python reference.
func TestChunkerMultilingualConformance(t *testing.T) {
	var fixture struct {
		Chunker []struct {
			Text      string   `json:"text"`
			MaxTokens int      `json:"max_tokens"`
			Overlap   int      `json:"overlap"`
			Chunks    []string `json:"chunks"`
		} `json:"chunker"`
	}
	conform.Case(t, "multilingual.json", &fixture)

	if len(fixture.Chunker) == 0 {
		t.Fatal("no multilingual chunker cases loaded")
	}
	for i, c := range fixture.Chunker {
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
