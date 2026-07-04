package structure

import (
	"encoding/json"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// BuildStructure is proven against the shared fixture — every case must match
// the Python arbiter (citenexus.evidence.structure.build_structure) exactly.
// Load the fixture, assert over ALL cases, no leniency. Produced and expected
// are both marshalled to canonical JSON and compared byte-for-byte.
func TestStructureConformance(t *testing.T) {
	var fixture struct {
		Cases []struct {
			Name          string          `json:"name"`
			DocumentID    string          `json:"document_id"`
			StructureType string          `json:"structure_type"`
			Blocks        []Block         `json:"blocks"`
			Expected      json.RawMessage `json:"expected"`
		} `json:"cases"`
	}
	conform.Case(t, "structure.json", &fixture)

	if len(fixture.Cases) == 0 {
		t.Fatal("no structure cases loaded")
	}

	for _, c := range fixture.Cases {
		var want Index
		if err := json.Unmarshal(c.Expected, &want); err != nil {
			t.Fatalf("%s: unmarshal expected: %v", c.Name, err)
		}
		doc := Doc{
			DocumentID:    c.DocumentID,
			StructureType: c.StructureType,
			Blocks:        c.Blocks,
		}
		got := BuildStructure(doc)

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
