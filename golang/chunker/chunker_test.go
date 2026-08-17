package chunker

import (
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// expectedChunkerCases pins the size of conformance/cases/chunker.json.
const expectedChunkerCases = 7

func TestChunkerVectorCount(t *testing.T) {
	var cases []struct {
		MaxTokens int `json:"max_tokens"`
	}
	conform.Case(t, "chunker.json", &cases)
	if len(cases) != expectedChunkerCases {
		t.Fatalf("chunker.json: got %d cases, want %d", len(cases), expectedChunkerCases)
	}
}

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

	if len(cases) != expectedChunkerCases {
		t.Fatalf("chunker.json: got %d cases, want %d", len(cases), expectedChunkerCases)
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
