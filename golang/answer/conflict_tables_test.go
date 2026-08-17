package answer

import (
	"reflect"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// TestConflictTablesMatchConformance pins the embedded copy to the canonical
// conformance/conflict.json (ADR-0010 tier 2: one definition, every port's copy
// GENERATED). The copy is written by python/scripts/gen_conflict_tables.py; this
// turns "someone hand-edited it" or "someone forgot to regenerate" into a loud
// failure instead of a silent divergence from the cross-language contract.
func TestConflictTablesMatchConformance(t *testing.T) {
	var canonical ConflictTables
	conform.Data(t, "conflict.json", &canonical)

	got := LoadConflictTables()
	if !reflect.DeepEqual(got, canonical) {
		t.Fatalf("embedded conflict tables diverged from conformance/conflict.json\n got  %+v\n want %+v", got, canonical)
	}
}

// TestConflictTableSizes pins the table sizes independently of the file, so a
// vector silently dropped from the canonical file is still caught here.
func TestConflictTableSizes(t *testing.T) {
	tables := LoadConflictTables()
	for _, c := range []struct {
		name string
		got  int
		want int
	}{
		{"negations", len(tables.Negations), 21},
		{"antonyms", len(tables.Antonyms), 30},
		{"report_bigrams", len(tables.ReportBigrams), 11},
		{"scope_markers", len(tables.ScopeMarkers), 27},
		{"measurement_units", len(tables.MeasurementUnits), 73},
	} {
		if c.got != c.want {
			t.Errorf("%s: got %d entries, want %d", c.name, c.got, c.want)
		}
	}
}

// TestConflictThresholdsArePinned guards the number ADR-0007 says matters most:
// relaxing MaxResidual to 2 buys 4pp of recall and pays 15pp of false
// abstention, and in strict mode a false conflict is a FALSE REFUSAL.
func TestConflictThresholdsArePinned(t *testing.T) {
	th := LoadConflictTables().Thresholds
	if th.MaxResidual != 1 {
		t.Errorf("MaxResidual = %d, want 1", th.MaxResidual)
	}
	if th.SubjectOverlap != 0.60 {
		t.Errorf("SubjectOverlap = %v, want 0.60", th.SubjectOverlap)
	}
	if th.MaxSymdiff != 3 || th.MinContent != 3 {
		t.Errorf("MaxSymdiff/MinContent = %d/%d, want 3/3", th.MaxSymdiff, th.MinContent)
	}
	if th.DuplicateJaccard != 0.80 {
		t.Errorf("DuplicateJaccard = %v, want 0.80", th.DuplicateJaccard)
	}
	if th.TopK != 6 || th.DuplicateMaxLengthDelta != 2 {
		t.Errorf("TopK/DuplicateMaxLengthDelta = %d/%d, want 6/2", th.TopK, th.DuplicateMaxLengthDelta)
	}
}

// TestAntonymSetIsSymmetrised: the canonical file stores each pair in ONE
// direction only, so the reader must symmetrise or half the antonym conflicts
// go undetected depending on candidate order.
func TestAntonymSetIsSymmetrised(t *testing.T) {
	set := ConflictAntonymSet()
	if len(set) != 60 {
		t.Fatalf("symmetrised antonyms = %d, want 60", len(set))
	}
	for pair := range set {
		if _, ok := set[[2]string{pair[1], pair[0]}]; !ok {
			t.Errorf("missing reverse of %v", pair)
		}
	}
}
