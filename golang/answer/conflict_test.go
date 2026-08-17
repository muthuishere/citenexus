package answer

import (
	"fmt"
	"testing"

	"github.com/muthuishere/citenexus/golang/internal/conform"
)

// The ADR-0007 conflict vectors, asserted as a BINDING contract.
//
// conformance/cases/conflict.json is the cross-port contract for conflict
// surfacing (ADR-0010 tier 1: native in Python, Go and JS, byte-identical).
// python/tests/answer/test_conflict_conformance.py holds the reference to
// exactly this file; this holds the Go port to it, reading the committed JSON as
// opaque data and asserting every one of its 102 vectors — verdict AND rule
// name.

type conflictVector struct {
	Domain    string  `json:"domain"`
	Label     string  `json:"label"`
	Left      string  `json:"left"`
	Right     string  `json:"right"`
	Conflict  bool    `json:"conflict"`
	Rule      *string `json:"rule"`
	Collapses bool    `json:"collapses"`
}

var conflictPairBuckets = []string{
	"true_conflicts",
	"hard_negatives",
	"unrelated",
	"heldout_conflicts",
	"heldout_negatives",
}

// expectedConflictCounts pins the bucket sizes. A vector silently dropped from a
// bucket is a weakened contract that no per-case assertion can see.
var expectedConflictCounts = map[string]int{
	"true_conflicts":          27,
	"hard_negatives":          27,
	"unrelated":               22,
	"heldout_conflicts":       5,
	"heldout_negatives":       10,
	"near_duplicates":         9,
	"identifier_tokenization": 2,
}

func loadConflictVectors(t *testing.T) map[string][]conflictVector {
	t.Helper()
	var vectors map[string][]conflictVector
	conform.Case(t, "conflict.json", &vectors)
	return vectors
}

func TestConflictVectorBucketNamesAndSizes(t *testing.T) {
	vectors := loadConflictVectors(t)
	if len(vectors) != len(expectedConflictCounts) {
		t.Fatalf("bucket set mismatch: got %d buckets, want %d", len(vectors), len(expectedConflictCounts))
	}
	total := 0
	for name, want := range expectedConflictCounts {
		got, ok := vectors[name]
		if !ok {
			t.Fatalf("missing bucket %q", name)
		}
		if len(got) != want {
			t.Errorf("bucket %q: got %d vectors, want %d", name, len(got), want)
		}
		total += want
	}
	if total != 102 {
		t.Fatalf("pinned bucket sizes sum to %d, want 102", total)
	}
}

// TestConflictPairwiseVectors asserts the verdict AND the rule name for every
// pairwise vector.
func TestConflictPairwiseVectors(t *testing.T) {
	vectors := loadConflictVectors(t)
	for _, bucket := range conflictPairBuckets {
		for i, c := range vectors[bucket] {
			t.Run(fmt.Sprintf("%s-%d", bucket, i), func(t *testing.T) {
				finding, ok := DetectConflict(c.Left, c.Right)
				if ok != c.Conflict {
					t.Fatalf("%s/%s: expected conflict=%v\n  left:  %s\n  right: %s\n  got:   %+v",
						c.Domain, c.Label, c.Conflict, c.Left, c.Right, finding)
				}
				wantRule := ""
				if c.Rule != nil {
					wantRule = *c.Rule
				}
				gotRule := ""
				if ok {
					gotRule = finding.Rule
				}
				if gotRule != wantRule {
					t.Fatalf("%s/%s: rule %q, want %q", c.Domain, c.Label, gotRule, wantRule)
				}
			})
		}
	}
}

// TestConflictNearDuplicateVectors pins the surface-clone collapse verdicts.
func TestConflictNearDuplicateVectors(t *testing.T) {
	vectors := loadConflictVectors(t)
	for i, c := range vectors["near_duplicates"] {
		t.Run(fmt.Sprintf("near_duplicates-%d", i), func(t *testing.T) {
			_, collapsed := IsNearDuplicate(c.Left, c.Right)
			if collapsed != c.Collapses {
				t.Fatalf("%s: expected collapses=%v\n  left:  %s\n  right: %s",
					c.Label, c.Collapses, c.Left, c.Right)
			}
		})
	}
}

// TestConflictIdentifierTokenizationVectors: a letter-leading token containing
// digits ("p50") is an identifier, not a value.
func TestConflictIdentifierTokenizationVectors(t *testing.T) {
	vectors := loadConflictVectors(t)
	for i, c := range vectors["identifier_tokenization"] {
		t.Run(fmt.Sprintf("identifier_tokenization-%d", i), func(t *testing.T) {
			finding, ok := DetectConflict(c.Left, c.Right)
			if ok != c.Conflict {
				t.Fatalf("expected conflict=%v\n  left:  %s\n  right: %s\n  got: %+v",
					c.Conflict, c.Left, c.Right, finding)
			}
		})
	}
}

// TestConflictDetectionIsSymmetric: every pairwise vector must hold with the
// arguments swapped. A port that only reproduces one argument order has not
// reproduced the contract — post-fusion candidates are compared in an arbitrary
// order.
func TestConflictDetectionIsSymmetric(t *testing.T) {
	vectors := loadConflictVectors(t)
	for _, bucket := range conflictPairBuckets {
		for _, c := range vectors[bucket] {
			if _, ok := DetectConflict(c.Right, c.Left); ok != c.Conflict {
				t.Errorf("%s/%s: asymmetric verdict\n  left:  %s\n  right: %s",
					bucket, c.Label, c.Left, c.Right)
			}
		}
	}
}

// TestConflictFoldIsOneRuleNotAStemmer pins the deliberate single-rule fold.
func TestConflictFoldIsOneRuleNotAStemmer(t *testing.T) {
	for _, c := range []struct{ in, want string }{
		{"requires", "require"},
		{"conserves", "conserve"},
		{"attracts", "attract"},
		{"class", "class"},       // -ss
		{"status", "status"},     // -us
		{"analysis", "analysis"}, // -is
		{"gas", "gas"},           // too short
		{"is", "is"},
		{"ties", "tie"},
		{"policy", "policy"},
	} {
		if got := foldConflictToken(c.in); got != c.want {
			t.Errorf("fold(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

// TestConflictUnicodeSpaceBetweenNumberAndUnit is the one behaviour NO
// conformance vector covers, because all 102 use an ASCII space.
//
// Python's `\s` (and JavaScript's) is Unicode-aware; Go's RE2 `\s` is
// [\t\n\f\r ] and nothing else. A non-breaking or narrow no-break space between
// a number and its unit is ordinary typography — it arrives from PDF and HTML
// extraction constantly — and a raw `\s` here would silently drop the unit in Go
// alone. The value rule requires a.units == b.units, so the ports would then
// disagree on a real corpus while every vector stayed green. Verified against
// the reference by execution: Python attaches "mg" in both spellings.
func TestConflictUnicodeSpaceBetweenNumberAndUnit(t *testing.T) {
	// ASCII space, NBSP, narrow NBSP, thin space, ideographic space, vertical tab.
	for _, space := range []string{" ", "\u00a0", "\u202f", "\u2009", "\u3000", "\v"} {
		left := "The recommended maintenance dose is 12" + space + "mg."
		right := "The recommended maintenance dose is 30" + space + "mg."
		finding, ok := DetectConflict(left, right)
		if !ok || finding.Rule != "value" || finding.Detail != "12 vs 30" {
			t.Errorf("space %q: got %+v (ok=%v), want value/12 vs 30", space, finding, ok)
		}
		// Different units with the same spacing must NOT conflict.
		if _, ok := DetectConflict(left, "The recommended maintenance dose is 30"+space+"ml."); ok {
			t.Errorf("space %q: mg vs ml must not conflict", space)
		}
	}
}

// TestConflictNumberNormalization pins the comma/trailing-zero rules: EVERY
// comma is stripped, not just the first.
func TestConflictNumberNormalization(t *testing.T) {
	for _, c := range []struct{ in, want string }{
		{"1,234,567", "1234567"},
		{"5,000.00", "5000"},
		{"2,000.50", "2000.5"},
		{"0.10", "0.1"},
		{"30", "30"},
	} {
		if got := normalizeConflictNumber(c.in); got != c.want {
			t.Errorf("normalize(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

// TestConflictDescribeFormat pins the one-line rendering byte-for-byte.
func TestConflictDescribeFormat(t *testing.T) {
	pair := ConflictPair{Left: 0, Right: 1, Finding: ConflictFinding{Rule: "value", Detail: "12 vs 30"}}
	if got, want := pair.Describe("filing-q1", "filing-q1-restated"),
		"value: filing-q1 vs filing-q1-restated (12 vs 30)"; got != want {
		t.Fatalf("Describe() = %q, want %q", got, want)
	}
	lines := DescribeConflicts([]ConflictPair{pair}, []string{"filing-q1", "filing-q1-restated"})
	if len(lines) != 1 || lines[0] != "value: filing-q1 vs filing-q1-restated (12 vs 30)" {
		t.Fatalf("DescribeConflicts() = %q", lines)
	}
}

// TestConflictDescribeIsDeterministic guards the one place Go map ordering could
// leak into output: the antonym detail iterates two set differences.
func TestConflictDescribeIsDeterministic(t *testing.T) {
	left := "The zoning variance was approved by the council."
	right := "The zoning variance was rejected by the council."
	first, ok := DetectConflict(left, right)
	if !ok || first.Rule != "antonym" {
		t.Fatalf("fixture must produce an antonym finding, got %+v (ok=%v)", first, ok)
	}
	for i := 0; i < 200; i++ {
		again, ok := DetectConflict(left, right)
		if !ok || again != first {
			t.Fatalf("nondeterministic finding on run %d: %+v vs %+v", i, again, first)
		}
	}
}

// TestFindConflictsWindow pins the CONFLICT_TOP_K window: a conflict outside the
// first TopK passages is not reported.
func TestFindConflictsWindow(t *testing.T) {
	if got := ConflictTopK(); got != 6 {
		t.Fatalf("ConflictTopK() = %d, want 6", got)
	}
	filler := "Unrelated boilerplate about shipping schedules and warehouse capacity."
	passages := []string{
		"The dividend for the period was 12 cents per share.",
		filler + " one", filler + " two", filler + " three", filler + " four", filler + " five",
		"The dividend for the period was 30 cents per share.",
	}
	if pairs := FindConflicts(passages); len(pairs) != 0 {
		t.Fatalf("conflict outside the top-k window was reported: %+v", pairs)
	}
	inWindow := []string{passages[0], passages[6]}
	pairs := FindConflicts(inWindow)
	if len(pairs) != 1 || pairs[0].Left != 0 || pairs[0].Right != 1 || pairs[0].Finding.Rule != "value" {
		t.Fatalf("FindConflicts() = %+v", pairs)
	}
}

// TestCollapseNearDuplicates keeps the first of a clone set, in order.
func TestCollapseNearDuplicates(t *testing.T) {
	passages := []string{
		"The vendor shall notify the customer within 30 days of a breach.",
		"The vendor shall notify the customer within 30 days of a breach.",
		"Employees may carry over five vacation days into the next year.",
	}
	got := CollapseNearDuplicates(passages)
	if len(got) != 2 || got[0] != 0 || got[1] != 2 {
		t.Fatalf("CollapseNearDuplicates() = %v, want [0 2]", got)
	}
}
