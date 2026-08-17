package gate

import (
	"reflect"
	"sort"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

type v2Case struct {
	Name      string `json:"name"`
	Passage   string `json:"passage"`
	Answer    string `json:"answer"`
	Supported bool   `json:"supported"`
}

type v2Fixture struct {
	Attacks  []v2Case `json:"attacks"`
	Controls []v2Case `json:"controls"`
}

// expectedFaithfulV2Counts pins the bucket sizes of
// conformance/cases/faithful_v2.json: nine adversarial attacks and thirty
// controls. A dropped attack is a silently weakened ADR-0009 contract.
var expectedFaithfulV2Counts = map[string]int{
	"attacks":  9,
	"controls": 30,
}

func loadFaithfulV2(t *testing.T) v2Fixture {
	t.Helper()
	var fixture v2Fixture
	conform.Case(t, "faithful_v2.json", &fixture)
	return fixture
}

func assertFaithfulV2Counts(t *testing.T, fixture v2Fixture) {
	t.Helper()
	for name, got := range map[string]int{
		"attacks":  len(fixture.Attacks),
		"controls": len(fixture.Controls),
	} {
		if want := expectedFaithfulV2Counts[name]; got != want {
			t.Fatalf("faithful_v2.json bucket %q: got %d vectors, want %d", name, got, want)
		}
	}
}

func TestFaithfulV2VectorBucketSizes(t *testing.T) {
	assertFaithfulV2Counts(t, loadFaithfulV2(t))
}

// TestIsSupportedV2Conformance is the ADR-0009 contract: every verdict in
// conformance/cases/faithful_v2.json must be reproduced exactly. The attacks are
// nine false answers that the frozen v1 predicate accepts 9/9; the controls are
// legitimately-supported answers in four shapes (verbatim, subspan,
// punctuation/case noise, interior-word compression) that must stay accepted —
// the measured false-rejection rate is 0.0%.
func TestIsSupportedV2Conformance(t *testing.T) {
	fixture := loadFaithfulV2(t)
	assertFaithfulV2Counts(t, fixture)

	for _, group := range []struct {
		label string
		cases []v2Case
	}{{"attack", fixture.Attacks}, {"control", fixture.Controls}} {
		for _, c := range group.cases {
			got := IsSupportedV2(c.Answer, c.Passage)
			if got != c.Supported {
				t.Errorf("%s %q: IsSupportedV2 = %v, want %v\n  passage: %q\n  answer:  %q",
					group.label, c.Name, got, c.Supported, c.Passage, c.Answer)
			}
		}
	}
}

// TestV2IsNarrowerThanV1 pins the ADR-0009 claim that the new predicate is
// strictly narrower: anything v2 accepts, the frozen v1 predicate already
// accepted. If this ever fails, v2 has become a different predicate rather than
// a tightening of the same one.
func TestV2IsNarrowerThanV1(t *testing.T) {
	fixture := loadFaithfulV2(t)
	assertFaithfulV2Counts(t, fixture)

	all := append(append([]v2Case{}, fixture.Attacks...), fixture.Controls...)
	for _, c := range all {
		if IsSupportedV2(c.Answer, c.Passage) && !IsSupported(c.Answer, c.Passage) {
			t.Errorf("%q: v2 accepted what v1 rejected — v2 must be strictly narrower", c.Name)
		}
	}
}

// TestAttacksStillPassV1 documents WHY v2 exists: the frozen predicate accepts
// all nine adversarial answers. It also guards the requirement that IsSupported
// stays byte-identical.
func TestAttacksStillPassV1(t *testing.T) {
	fixture := loadFaithfulV2(t)
	assertFaithfulV2Counts(t, fixture)

	accepted := 0
	for _, c := range fixture.Attacks {
		if IsSupported(c.Answer, c.Passage) {
			accepted++
		}
	}
	if accepted != len(fixture.Attacks) {
		t.Fatalf("frozen v1 predicate accepted %d/%d attacks; SPEC-PORTS-v1 §4 pins it at all of them",
			accepted, len(fixture.Attacks))
	}
}

// TestPolarityTableMatchesConformance pins the embedded copy to the canonical
// conformance/polarity.json (ADR-0010 tier 2: one definition, generated copies,
// never hand-maintained divergence).
func TestPolarityTableMatchesConformance(t *testing.T) {
	var canonical struct {
		Languages []string `json:"languages"`
		Markers   []string `json:"markers"`
	}
	conform.Data(t, "polarity.json", &canonical)

	got := make([]string, 0, len(PolarityMarkers()))
	for m := range PolarityMarkers() {
		got = append(got, m)
	}
	want := append([]string{}, canonical.Markers...)
	sort.Strings(got)
	sort.Strings(want)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("embedded polarity.json diverged from conformance/polarity.json:\n got  %v\n want %v", got, want)
	}
}

// TestAlignShape checks the alignment metadata itself, not just the boolean —
// the span is what a caller cites, so its indices are part of the contract.
func TestAlignShape(t *testing.T) {
	passage := []string{"the", "contractor", "shall", "maintain", "liability", "insurance", "at", "all", "times"}

	span, ok := Align([]string{"contractor", "maintain", "insurance"}, passage)
	if !ok {
		t.Fatal("expected an alignment for an ordered, gapped subsequence")
	}
	if span.Start != 1 || span.End != 5 || span.TotalGap != 2 || span.MaxGap != 1 {
		t.Fatalf("alignment = %+v, want {Start:1 End:5 TotalGap:2 MaxGap:1}", span)
	}

	if _, ok := Align([]string{"insurance", "contractor"}, passage); ok {
		t.Fatal("out-of-order tokens must not align")
	}
	if _, ok := Align(nil, passage); ok {
		t.Fatal("an empty claim must not align")
	}
	if _, ok := Align([]string{"contractor"}, nil); ok {
		t.Fatal("an empty passage must not align")
	}
}

// TestGapBudgetIsPinned proves the pinned budget is load-bearing: a claim whose
// interior gap exceeds MaxSingleGap is rejected, one inside it is accepted.
func TestGapBudgetIsPinned(t *testing.T) {
	if MaxSingleGap != 4 || MaxTotalGap != 8 {
		t.Fatalf("gap budget drifted: (%d, %d), want (4, 8)", MaxSingleGap, MaxTotalGap)
	}
	passage := []string{"a", "x", "x", "x", "x", "b"}
	if _, ok := Align([]string{"a", "b"}, passage); !ok {
		t.Fatal("a gap of exactly MaxSingleGap must align")
	}
	passage = append([]string{"a", "x", "x", "x", "x", "x"}, "b")
	if _, ok := Align([]string{"a", "b"}, passage); ok {
		t.Fatal("a gap over MaxSingleGap must not align")
	}
}
