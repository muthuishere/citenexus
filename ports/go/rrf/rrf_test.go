package rrf

import (
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus-go/internal/conform"
)

// Reciprocal Rank Fusion is proven against the shared fixture — every case must
// match the Python reference exactly (citenexus.retrieve.fusion.rrf_fuse). This
// test follows the §4 exemplar: load conformance/cases/rrf.json, assert exact
// output over ALL cases, no leniency.
func TestRRFConformance(t *testing.T) {
	var cases []struct {
		Lists [][]string `json:"lists"`
		K     int        `json:"k"`
		Fused []string   `json:"fused"`
	}
	conform.Case(t, "rrf.json", &cases)

	if len(cases) == 0 {
		t.Fatal("no rrf cases loaded")
	}
	for i, c := range cases {
		got := Fuse(c.Lists, c.K)
		want := c.Fused
		if want == nil {
			want = []string{}
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("case %d: Fuse(%v, %d) = %v, want %v", i, c.Lists, c.K, got, want)
		}
	}
}
