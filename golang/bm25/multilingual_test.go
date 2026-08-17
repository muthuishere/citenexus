package bm25

import (
	"math"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// expectedMultilingualBm25Cases pins the "bm25" bucket of
// conformance/cases/multilingual.json as this package consumes it. Four packages
// read that file; each pins its own bucket independently.
const expectedMultilingualBm25Cases = 3

func TestMultilingualBm25VectorCount(t *testing.T) {
	var fixture struct {
		Bm25 []struct {
			Name string `json:"name"`
		} `json:"bm25"`
	}
	conform.Case(t, "multilingual.json", &fixture)
	if len(fixture.Bm25) != expectedMultilingualBm25Cases {
		t.Fatalf("multilingual.json bucket %q: got %d vectors, want %d",
			"bm25", len(fixture.Bm25), expectedMultilingualBm25Cases)
	}
}

// The multilingual anti-drift corpus (ADR-0006) run through BM25: a query like
// "İstanbul" tokenizes to {i, stanbul} in the reference, so a port that lowers
// İ to a bare "i" ranks the rows differently and fails these vectors.
func TestBm25MultilingualConformance(t *testing.T) {
	var fixture struct {
		Bm25 []struct {
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
		} `json:"bm25"`
	}
	conform.Case(t, "multilingual.json", &fixture)

	if len(fixture.Bm25) != expectedMultilingualBm25Cases {
		t.Fatalf("multilingual.json bucket %q: got %d vectors, want %d",
			"bm25", len(fixture.Bm25), expectedMultilingualBm25Cases)
	}
	for _, c := range fixture.Bm25 {
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
