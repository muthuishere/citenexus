// ADR-0009 — ordered containment with a polarity guard.
//
// IsSupported is set containment, and set containment is closed under two
// meaning-changing operations: reordering (inverting the parties to an
// obligation is a token-set identity) and deletion ("not" is a token, so
// dropping a negation yields a strict subset). Measured in
// spikes/library-stress/: nine false answers accepted 9/9, identically in
// Python, Go and JS.
//
// IsSupportedV2 requires the claim's tokens to appear IN ORDER within a bounded
// interior gap, and requires any polarity marker inside the matched span to
// survive into the claim. It is strictly narrower than IsSupported — anything it
// accepts, the frozen predicate accepted — so it can only reduce what passes.
//
// ADR-0010 tier 1: this is native per port, not the Rust core. It is an integer
// dynamic programme over two token arrays — NO regex — so nothing here depends
// on RE2 vs PCRE semantics.
//
// The polarity table is ADR-0010 tier 2: shared data, per-port code. polarity.json
// is a copy of conformance/polarity.json, EMBEDDED so this module is
// self-contained when consumed as a Go dependency (a filesystem read of the
// shared conformance/ dir would not exist in the module cache). TestPolarityTableMatchesConformance
// pins the copy to the canonical file.
package gate

import (
	_ "embed"
	"encoding/json"
	"sync"

	"github.com/muthuishere/citenexus/golang/tokenize"
)

//go:embed polarity.json
var polarityJSON []byte

// Pinned, not configurable. A caller who widens the budget silently weakens the
// guarantee, and a conformance vector cannot pin a value the caller controls.
// The ADR-0009 spike swept the budget and found the knee at (3, 6); (4, 8)
// leaves headroom for compressed answers. The attacks are insensitive to it —
// they fail on order, not on gap size.
const (
	MaxSingleGap = 4
	MaxTotalGap  = 8
)

var (
	polarityOnce    sync.Once
	polarityMarkers map[string]struct{}
)

// loadPolarityMarkers parses and caches the pinned polarity marker set from the
// embedded copy of conformance/polarity.json.
func loadPolarityMarkers() map[string]struct{} {
	polarityOnce.Do(func() {
		var table struct {
			Languages []string `json:"languages"`
			Markers   []string `json:"markers"`
		}
		if err := json.Unmarshal(polarityJSON, &table); err != nil {
			panic("gate: unmarshal polarity.json: " + err.Error())
		}
		set := make(map[string]struct{}, len(table.Markers))
		for _, m := range table.Markers {
			set[m] = struct{}{}
		}
		polarityMarkers = set
	})
	return polarityMarkers
}

// PolarityMarkers returns a copy of the pinned polarity marker set: tokens whose
// DELETION flips the meaning of a claim.
func PolarityMarkers() map[string]struct{} {
	src := loadPolarityMarkers()
	out := make(map[string]struct{}, len(src))
	for k := range src {
		out[k] = struct{}{}
	}
	return out
}

// Alignment records where a claim matched inside a passage, in token indices.
type Alignment struct {
	Start    int // index of the first matched passage token
	End      int // index of the last matched passage token (inclusive)
	TotalGap int // passage tokens skipped strictly inside the span
	MaxGap   int // the largest single skip inside the span
}

// cell is one dynamic-programming state: the best (totalGap, maxGap, start) for
// a claim prefix ending at this passage index.
type cell struct {
	total int
	max   int
	start int
	ok    bool
}

// Align returns the minimal-gap ordered alignment of claimTokens into
// passageTokens under the pinned budget, or ok=false when the claim is not an
// order- and multiplicity-preserving subsequence of the passage within it.
//
// O(len(claim) * len(passage)) integer DP. No regex, no recursion — parity with
// the Python reference citenexus.answer.verify.align.
func Align(claimTokens, passageTokens []string) (Alignment, bool) {
	return AlignWithBudget(claimTokens, passageTokens, MaxSingleGap, MaxTotalGap)
}

// AlignWithBudget is Align with an explicit gap budget. The shipped predicate
// always uses the pinned constants; the budget is a parameter only so the
// budget sweep in the spike stays reproducible.
func AlignWithBudget(claimTokens, passageTokens []string, maxSingleGap, maxTotalGap int) (Alignment, bool) {
	if len(claimTokens) == 0 || len(passageTokens) == 0 {
		return Alignment{}, false
	}

	n, m := len(claimTokens), len(passageTokens)
	state := make([]cell, m)

	// The claim's first token may start anywhere it occurs.
	for j := 0; j < m; j++ {
		if passageTokens[j] == claimTokens[0] {
			state[j] = cell{total: 0, max: 0, start: j, ok: true}
		}
	}

	next := make([]cell, m)
	for i := 1; i < n; i++ {
		for j := range next {
			next[j] = cell{}
		}
		var best cell // running best over k < j
		bestK := -1
		for j := 0; j < m; j++ {
			// fold position j-1 into the running best before using it for j
			if j > 0 {
				prev := state[j-1]
				if prev.ok && (!best.ok || prev.total < best.total) {
					best, bestK = prev, j-1
				}
			}
			if passageTokens[j] != claimTokens[i] || !best.ok {
				continue
			}
			gap := j - bestK - 1
			if gap > maxSingleGap {
				continue
			}
			total := best.total + gap
			if total > maxTotalGap {
				continue
			}
			mx := best.max
			if gap > mx {
				mx = gap
			}
			next[j] = cell{total: total, max: mx, start: best.start, ok: true}
		}
		state, next = next, state
		anyOK := false
		for _, s := range state {
			if s.ok {
				anyOK = true
				break
			}
		}
		if !anyOK {
			return Alignment{}, false
		}
	}

	// min over (total_gap, end index) — ties break to the leftmost end.
	found := false
	var bestCell cell
	bestEnd := -1
	for j := 0; j < m; j++ {
		s := state[j]
		if !s.ok {
			continue
		}
		if !found || s.total < bestCell.total {
			found, bestCell, bestEnd = true, s, j
		}
	}
	if !found {
		return Alignment{}, false
	}
	return Alignment{Start: bestCell.start, End: bestEnd, TotalGap: bestCell.total, MaxGap: bestCell.max}, true
}

// polarityPreserved is true when every polarity marker inside the matched span
// survives into the claim. Multiplicity matters: dropping one of two negations
// flips the meaning just as completely as dropping the only one.
func polarityPreserved(claimTokens, passageTokens []string, span Alignment) bool {
	markers := loadPolarityMarkers()
	matched := passageTokens[span.Start : span.End+1]

	inSpan := make(map[string]int)
	for _, tok := range matched {
		if _, isMarker := markers[tok]; isMarker {
			inSpan[tok]++
		}
	}
	if len(inSpan) == 0 {
		return true
	}
	inClaim := make(map[string]int, len(inSpan))
	for _, tok := range claimTokens {
		if _, tracked := inSpan[tok]; tracked {
			inClaim[tok]++
		}
	}
	for tok, want := range inSpan {
		if inClaim[tok] < want {
			return false
		}
	}
	return true
}

// IsSupportedV2 is order- and multiplicity-aware containment plus the polarity
// guard (ADR-0009). Pure, deterministic, offline, and strictly narrower than
// IsSupported.
func IsSupportedV2(answer, passage string) bool {
	claimTokens := tokenize.TokenizeV2(answer)
	passageTokens := tokenize.TokenizeV2(passage)
	span, ok := Align(claimTokens, passageTokens)
	if !ok {
		return false
	}
	return polarityPreserved(claimTokens, passageTokens, span)
}
