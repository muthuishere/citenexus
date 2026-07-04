package graph

import (
	"encoding/json"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// BuildComentionGraph is proven against the shared fixture — every case must
// match the Python arbiter (citenexus.graph.store.build_comention_graph)
// exactly. Follows the gate/tokenize exemplar: load the fixture, assert over ALL
// cases, no leniency. Produced and expected are both marshalled to canonical
// JSON (field order + null/[] normalized) and compared byte-for-byte.
func TestComentionGraphConformance(t *testing.T) {
	var fixture struct {
		Cases []struct {
			Name     string          `json:"name"`
			Rows     []Row           `json:"rows"`
			Expected json.RawMessage `json:"expected"`
		} `json:"cases"`
	}
	conform.Case(t, "graph_comention.json", &fixture)

	if len(fixture.Cases) == 0 {
		t.Fatal("no graph_comention cases loaded")
	}

	for _, c := range fixture.Cases {
		var want Index
		if err := json.Unmarshal(c.Expected, &want); err != nil {
			t.Fatalf("%s: unmarshal expected: %v", c.Name, err)
		}
		got := BuildComentionGraph(c.Rows)

		gotJSON, err := json.Marshal(got)
		if err != nil {
			t.Fatalf("%s: marshal got: %v", c.Name, err)
		}
		wantJSON, err := json.Marshal(want)
		if err != nil {
			t.Fatalf("%s: marshal want: %v", c.Name, err)
		}
		if string(gotJSON) != string(wantJSON) {
			t.Errorf("%s:\n got  %s\n want %s", c.Name, gotJSON, wantJSON)
		}
	}
}
