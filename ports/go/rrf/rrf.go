// Package rrf is the pinned CiteNexus Reciprocal Rank Fusion (SPEC-PORTS-v1 §10).
//
// Definition (frozen contract): given several ranked lists of eu_id strings and
// a constant k (default 60), a candidate at zero-based rank in a list
// contributes 1/(k + rank + 1) to its eu_id's fused score. Contributions are
// summed across all lists. Results are ordered by descending fused score, with
// eu_id as an ascending tie-break — parity with the Python reference
// citenexus.retrieve.fusion.rrf_fuse.
package rrf

import "sort"

// DefaultK is the standard RRF constant.
const DefaultK = 60

// Fuse merges ranked lists of eu_id strings by Reciprocal Rank Fusion and
// returns the fused eu_id order (descending score, ascending eu_id tie-break).
func Fuse(lists [][]string, k int) []string {
	scores := map[string]float64{}
	order := []string{} // first-seen order, to make iteration deterministic

	for _, list := range lists {
		for rank, euID := range list {
			if _, seen := scores[euID]; !seen {
				order = append(order, euID)
			}
			scores[euID] += 1.0 / float64(k+rank+1)
		}
	}

	sort.SliceStable(order, func(i, j int) bool {
		a, b := order[i], order[j]
		if scores[a] != scores[b] {
			return scores[a] > scores[b]
		}
		return a < b
	})
	return order
}
