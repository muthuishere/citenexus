// Package authority is the standing of a SOURCE, kept strictly apart from
// grounding (ADR-0004). Go port of python/src/citenexus/domain/authority.py and
// the strict branch of python/src/citenexus/answer/authority.py.
//
// The faithfulness gate proves an answer's words came from the passage it cites.
// It cannot prove the passage had any standing to answer: on the live law corpus
// a Florida statute answered a Texas question with every claim verified. The
// gate was right; the source was not.
//
// Two rules carry over from the reference unchanged:
//
//   - Metadata-derived, never content-derived. A Policy maps caller-supplied
//     METADATA to a Tier and is never handed a passage, so authority cannot
//     become a function of the text by accident.
//   - Applied strictly AFTER grounding. Selection may reorder evidence and, under
//     a floor, drop it. It can never promote evidence grounding rejected, so the
//     only reachable behaviour change is more abstention.
//
// The zero Policy ranks every source equal and has no floor — the stable sort is
// then the identity, which is exactly the behaviour without authority. The
// feature is strictly opt-in.
package authority

import "sort"

// DefaultTierKey is the metadata key an ordered policy reads by default.
const DefaultTierKey = "authority_tier"

// UnknownRank is the rank of a tier the policy does not know — including missing
// metadata. Below every named tier, so an uncurated source can never sneak above
// a floor.
const UnknownRank = -1

// InsufficientAuthority is the refusal reason when the floor emptied the
// selection. Deliberately distinct from "no sufficiently relevant evidence
// found": "I found nothing" and "what I found has no standing" are different
// findings. Byte-identical to the Python reference.
const InsufficientAuthority = "no evidence at or above the required authority tier"

// Tier is a totally-ordered standing. Higher Rank = more authoritative. Name is
// reporting-only and never compared.
type Tier struct {
	Rank int
	Name string
}

// Outranks is true when t is strictly more authoritative than other.
func (t Tier) Outranks(other Tier) bool { return t.Rank > other.Rank }

// Policy is an ordering of tier names plus an optional floor. The zero value is
// the reference's default.v1 with no floor: every source unranked (rank 0).
type Policy struct {
	rank    map[string]int
	key     string
	minimum *Tier
}

// Ordered builds the reference's ordered.v1 policy. order is
// LEAST-authoritative first:
//
//	authority.Ordered([]string{"note", "proposal", "adopted"}, "")
//
// minimumTier is the strict-mode floor by tier name; "" means no floor. A floor
// name absent from order ranks UnknownRank, which floors nothing out of the
// named tiers — so name it from order.
func Ordered(order []string, minimumTier string) Policy {
	rank := make(map[string]int, len(order))
	for i, name := range order {
		rank[name] = i
	}
	p := Policy{rank: rank, key: DefaultTierKey}
	if minimumTier != "" {
		floor := p.TierNamed(minimumTier)
		p.minimum = &floor
	}
	return p
}

// WithKey returns a copy of p that reads its tier name from key instead of
// DefaultTierKey.
func (p Policy) WithKey(key string) Policy {
	p.key = key
	return p
}

// HasFloor is true when p enforces a minimum tier.
func (p Policy) HasFloor() bool { return p.minimum != nil }

// TierOf is the tier for a source's METADATA — never its text.
func (p Policy) TierOf(meta map[string]string) Tier {
	if p.rank == nil {
		return Tier{} // default.v1: everything unranked
	}
	key := p.key
	if key == "" {
		key = DefaultTierKey
	}
	name := meta[key]
	if r, ok := p.rank[name]; ok {
		return Tier{Rank: r, Name: name}
	}
	return Tier{Rank: UnknownRank, Name: name}
}

// TierNamed is the tier for a bare tier NAME — how a caller states a floor.
func (p Policy) TierNamed(name string) Tier {
	key := p.key
	if key == "" {
		key = DefaultTierKey
	}
	return p.TierOf(map[string]string{key: name})
}

// MeetsFloor is true when t is at or above the floor, or there is no floor.
func (p Policy) MeetsFloor(t Tier) bool {
	return p.minimum == nil || t.Rank >= p.minimum.Rank
}

// Selection is the selected candidates plus what authority did to get there.
type Selection[E any] struct {
	// Candidates are the floor survivors, most authoritative first; equal tiers
	// keep their input order.
	Candidates []E
	// Excluded were grounded but dropped for standing — kept so a refusal can say
	// what it declined to cite.
	Excluded []E
}

// FloorApplied is true when the floor actually WITHHELD evidence — not merely
// that a floor was configured, which would be true of every call and say
// nothing.
func (s Selection[E]) FloorApplied() bool { return len(s.Excluded) > 0 }

// Select is the reference's strict-mode select_by_authority: enforce the floor
// (below-floor candidates are excluded outright, with no fallback), then a
// STABLE sort by descending tier. No secondary key: one would silently re-rank
// equal-authority evidence.
//
// meta is the only view of a candidate Select gets, which is the ADR-0004 seam
// made structural: selection cannot read the passage.
func Select[E any](candidates []E, meta func(E) map[string]string, p Policy) Selection[E] {
	type ranked struct {
		c    E
		tier Tier
	}
	kept := make([]ranked, 0, len(candidates))
	excluded := []E{}
	for _, c := range candidates {
		t := p.TierOf(meta(c))
		if !p.MeetsFloor(t) {
			excluded = append(excluded, c)
			continue
		}
		kept = append(kept, ranked{c: c, tier: t})
	}
	sort.SliceStable(kept, func(i, j int) bool { return kept[i].tier.Rank > kept[j].tier.Rank })
	out := make([]E, len(kept))
	for i, r := range kept {
		out[i] = r.c
	}
	return Selection[E]{Candidates: out, Excluded: excluded}
}
