package bm25

import (
	"math"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// expectedBm25Cases pins the size of conformance/cases/bm25.json.
const expectedBm25Cases = 4

func TestBm25VectorCount(t *testing.T) {
	var cases []struct {
		Name string `json:"name"`
	}
	conform.Case(t, "bm25.json", &cases)
	if len(cases) != expectedBm25Cases {
		t.Fatalf("bm25.json: got %d cases, want %d", len(cases), expectedBm25Cases)
	}
}

// BM25 ranking is proven against the shared fixture — every case must match the
// Python reference exactly. Mirrors the tokenize EXEMPLAR: load the fixture,
// assert over ALL cases, no leniency, fail loudly on the first mismatch.
func TestBm25Conformance(t *testing.T) {
	var cases []struct {
		Name string `json:"name"`
		Rows []struct {
			EuID string `json:"eu_id"`
			Text string `json:"text"`
		} `json:"rows"`
		Query    string `json:"query"`
		Expected []struct {
			EuID  string  `json:"eu_id"`
			Score float64 `json:"score"`
		} `json:"expected"`
	}
	conform.Case(t, "bm25.json", &cases)

	if len(cases) != expectedBm25Cases {
		t.Fatalf("bm25.json: got %d cases, want %d", len(cases), expectedBm25Cases)
	}

	for _, c := range cases {
		rows := make([]Row, len(c.Rows))
		for i, r := range c.Rows {
			rows[i] = Row{EuID: r.EuID, Text: r.Text}
		}
		got := Rank(rows, c.Query)

		if len(got) != len(c.Expected) {
			t.Fatalf("case %q: got %d results, want %d (%+v)", c.Name, len(got), len(c.Expected), got)
		}
		for i, want := range c.Expected {
			if got[i].EuID != want.EuID {
				t.Fatalf("case %q: result[%d] eu_id = %q, want %q", c.Name, i, got[i].EuID, want.EuID)
			}
			if math.Abs(got[i].Score-want.Score) > 1e-9 {
				t.Fatalf("case %q: result[%d] score = %v, want %v", c.Name, i, got[i].Score, want.Score)
			}
		}
	}
}
