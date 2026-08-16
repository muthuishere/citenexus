# Design — authority in the deep-ask loop

## The question this design exists to answer

*Where in the loop does the floor go?*

The strict flow had one obvious seam: one retrieval, one grounded list, one
selection point between grounding and generation. The loop has no such single
moment — it retrieves N times, accumulates a pool, consults a decision model
between hops, and ends in a **single-EU** gate. So "apply `select_by_authority`
to the evidence" has at least three candidate placements, and they are not
equivalent.

## The three placements, and why two of them are wrong

### (A) Once at the end, over the finished pool — REJECTED

The tempting minimal diff: filter the pool in `_finish()` just before generating.
It is wrong on four counts, each independently disqualifying:

1. **Budget displacement.** The pool is capped at `max_evidence_units`. Junk
   pooled on hop 1 permanently occupies slots that an authority found on hop 3
   then cannot take — and hitting the cap *ends the loop* (`stop_reason=budget`).
   A below-floor source can therefore stop the search that would have found the
   binding one.
2. **The decider is fed unusable evidence.** `decide(question, [pool texts])`
   drives both `sufficient` (stop now) and `next_query` (where to look next). A
   Florida statute in the pool can make the model answer *"yes, sufficient"* and
   halt — the loop then abstains, having stopped searching **because of** the
   very evidence it is about to discard. The abstain is right; the failure to
   keep looking is not.
3. **Conflict manufacture.** `find_conflicts` runs over the pool window and, in
   strict mode, an unresolved conflict touching a cited EU is an abstain. A
   source with no standing must not be able to suppress one that has standing.
   The strict flow already settled this — its selection point sits *before*
   conflict detection precisely so that "a source with no standing cannot
   manufacture a conflict" — and the loop must not contradict it.
4. **The gate is single-EU, so "the end" is already too late.** In the strict
   flow there is one cited passage, so a final check is a complete check. Here
   *every* pooled EU is independently sufficient to carry a claim, and the
   generator has already been shown the concatenated pool. Filtering after
   generation would let a below-floor passage's words shape — and, where another
   EU happens to contain the same words, actually enter — the answer while a
   different EU takes the citation. That is the deep-flow analogue of the
   already-fixed "cite the source's words, not the context model's blurb" bug.

### (B) Inside the gate, per (claim, EU) — REJECTED

Rejected on ADR-0004 grounds, not convenience: it entangles standing with
grounding. `answer/verify.py` and the single-EU quantifier must stay a pure
statement about *where words came from*. A gate that knows about tiers is a gate
whose verdict is no longer independently testable, and ADR-0004 explicitly
rejected the fold-authority-into-grounding shape.

### (C) At pool admission, on every hop — CHOSEN

Each hop's rows are tiered from metadata and gated **before** entering the pool.
A below-floor EU is never a pool member, therefore:

- it cannot consume a `max_evidence_units` slot or trigger the budget stop;
- it is never shown to the decision model, so it cannot declare sufficiency or
  steer the next query;
- it cannot enter the conflict window;
- it cannot be the "some single EU" that satisfies a claim;
- it is not in the passage the generator sees.

This is the exact analogue of the strict flow's placement — *after* the evidence
exists, *before* anything reasons over it — applied at the loop's own equivalent
moment. The invariant is stated positively as: **the pool contains only evidence
that could legitimately be cited.** Everything downstream (decider, conflicts,
generator, gate, signals) then reads a pool it can trust, and no downstream stage
needs to know authority exists.

Ordering is applied at both ends of the same function: admission uses
`select_by_authority` for the floor, and `_finish` calls it once more over the
whole pool for the descending-tier reorder. The reorder matters because the gate
attributes a claim to the **first** EU that supports it — so the most
authoritative supporting EU gets the citation — and because the generator sees
the pool concatenated in that order.

## Reusing the one selection point

ADR-0004's structural commitment is *one* selection point, not two
implementations that can drift. `select_by_authority` was typed to `Candidate`;
the loop holds `_PooledEvidence`. Rather than copy the logic, the function
becomes generic over a minimal read-only protocol:

```python
class HasAuthorityMeta(Protocol):
    @property
    def authority_meta(self) -> str: ...
```

That protocol is *deliberately* the entire surface: it exposes the metadata and
**nothing else**. Authority code still structurally cannot read passage text,
which is the property ADR-0004 asked the seam to enforce. `AuthoritySelection`
becomes generic in the same parameter, so `.excluded` keeps its element type.

## Withheld ≠ exhausted

Today a hop that adds no new EU ends the loop (`no_new_evidence`, the
deterministic default stop). With admission gating, a hop can return rows and
still add nothing — because they were all withheld for standing. Treating that
as `no_new_evidence` would repeat, inside the loop, the very conflation ADR-0004
was written to end: *"I found nothing"* is not *"what I found has no standing."*

So a hop that admitted nothing **but withheld something** proceeds to the
decision model and may refine the query — the loop keeps looking for an
authority. It cannot run away: `max_hops`, `max_tool_calls` and `timeout_s` bound
it exactly as before, and the deterministic `no_new_evidence` stop is unchanged
for the case it actually describes (rows returned, all already seen).

## Signals

- `authority_floor_applied` — true iff the floor **withheld** at least one EU
  during the run. Not "a floor was configured" (that signal would be true on
  every strict call and carry no information), and it accumulates across hops
  rather than reporting only the last one.
- `authority_tier` — for a pooled answer, the **weakest** tier among the EUs
  actually cited. A deep answer rests on *all* of its sources; reporting the
  strongest would let one binding citation launder a weaker co-citation. Under
  "never wrong", the reported standing of an answer is the standing of its
  weakest support. (The strict flow cites one source, so its `authority_tier` is
  unchanged and the two definitions agree wherever they overlap.)
- The empty-pool refusal names `INSUFFICIENT_AUTHORITY` — the same constant the
  strict flow uses — whenever the floor withheld anything, and the pre-existing
  "no sufficiently relevant evidence found" otherwise. As in the strict flow,
  that refusal happens **before** any generator call.

## What this deliberately does not change

- `answer/verify.py`, `is_supported_v2`, `split_claims`, the single-EU
  quantifier: byte-identical. No authority module imports them; the gate never
  sees a tier.
- The strict flow: untouched. The generic-ing of `select_by_authority` is
  type-level only; `Candidate` satisfies the protocol and the runtime behaviour
  for existing calls is identical.
- Conformance fixtures and the pinned cross-port algorithms: untouched. Deep-ask
  is Python-only today, and no pinned algorithm changes.
- The subject-scope gap noted in the `authority-floor` design survives here too:
  a floor filters *source standing*, never *subject applicability*. A top-tier
  statute about the wrong subject is still a top-tier statute.
