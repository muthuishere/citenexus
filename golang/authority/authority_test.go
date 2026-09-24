package authority

import (
	"reflect"
	"testing"
)

type src struct {
	id   string
	meta map[string]string
}

func metaOf(s src) map[string]string { return s.meta }

func ids(ss []src) []string {
	out := []string{}
	for _, s := range ss {
		out = append(out, s.id)
	}
	return out
}

func tiered(id, tier string) src { return src{id, map[string]string{DefaultTierKey: tier}} }

func TestZeroPolicyIsTheIdentity(t *testing.T) {
	in := []src{tiered("a", "adopted"), tiered("b", "note"), {id: "c"}}
	sel := Select(in, metaOf, Policy{})
	if !reflect.DeepEqual(ids(sel.Candidates), []string{"a", "b", "c"}) || sel.FloorApplied() {
		t.Fatalf("%v", ids(sel.Candidates))
	}
}

func TestOrderedSortsStablyByTier(t *testing.T) {
	p := Ordered([]string{"note", "proposal", "adopted"}, "")
	in := []src{tiered("n1", "note"), tiered("a1", "adopted"), {id: "u"}, tiered("n2", "note"), tiered("a2", "adopted")}
	got := ids(Select(in, metaOf, p).Candidates)
	if want := []string{"a1", "a2", "n1", "n2", "u"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
}

func TestFloorExcludesBelowAndUnknown(t *testing.T) {
	p := Ordered([]string{"note", "proposal", "adopted"}, "proposal")
	sel := Select([]src{tiered("n", "note"), tiered("p", "proposal"), {id: "u"}, tiered("a", "adopted")}, metaOf, p)
	if !reflect.DeepEqual(ids(sel.Candidates), []string{"a", "p"}) {
		t.Fatalf("kept %v", ids(sel.Candidates))
	}
	if !reflect.DeepEqual(ids(sel.Excluded), []string{"n", "u"}) || !sel.FloorApplied() {
		t.Fatalf("excluded %v", ids(sel.Excluded))
	}
}

func TestWithKeyReadsAnotherColumn(t *testing.T) {
	p := Ordered([]string{"proposal", "adopted"}, "").WithKey("source_layer")
	if got := p.TierOf(map[string]string{"source_layer": "adopted"}); got.Rank != 1 || got.Name != "adopted" {
		t.Fatalf("%+v", got)
	}
	if got := p.TierOf(map[string]string{DefaultTierKey: "adopted"}); got.Rank != UnknownRank {
		t.Fatalf("read the default key: %+v", got)
	}
}
