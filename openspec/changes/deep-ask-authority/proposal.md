## Why

The `authority-floor` change closed a measured defect on the strict flow: on the
live `examples/law-authority` corpus, **4 of 8 answered questions cited an
out-of-jurisdiction source** — a **Florida** statute answering a **Texas**
question, with the faithfulness gate passing it *correctly* (the words really
were verbatim in the cited passage). After the floor: **zero** out-of-jurisdiction
citations, `abstain_when_no_evidence` 33% → 100%.

That floor covers **only the strict flow**. `authority-floor` recorded the gap
itself (tasks.md 4.7, "KNOWN NON-COVERAGE"): `strategy="deep"`
(`AgenticAnswerFlow`) never receives the `AuthorityPolicy`. So the exact wrong
answer the floor now prevents on the default path is **still reachable one
keyword away**:

```python
rag.ask("What is the notice period to end a month-to-month tenancy in Texas?",
        strategy="deep")   # -> can still answer from the Florida statute
```

Under the owner's ruling — *"we never want wrong at all, it's okay we can say
don't know"* — a guarantee that holds on one strategy and not the other is not a
guarantee. It is a hole with a flag on it.

Deep-ask is in fact the *more* exposed path, for two structural reasons:

1. **The pool is cumulative.** The loop gathers EUs across hops into one pool
   capped by `max_evidence_units`. A below-floor EU does not merely sit there —
   it consumes a slot, it is shown to the decision model (so it can declare the
   evidence "sufficient" and stop the search early, or steer `next_query`), and
   it can manufacture a conflict.
2. **The gate is single-EU.** Every claim must fit inside *some single* pooled
   EU. So **any** EU in the pool is sufficient, on its own, to carry a claim into
   the answer. There is no "top passage" whose standing could be checked once at
   the end; a below-floor EU in the pool is a below-floor EU that can answer.

## What Changes

- **`AgenticAnswerFlow` takes an `AuthorityPolicy`**, exactly as `AnswerFlow`
  does (`authority=`, defaulting to `default.v1` with no floor), and `CiteNexus`
  passes the *same policy object* it already builds for the strict flow. No new
  caller ceremony, no second config section: `strategy="deep"` inherits whatever
  `strategy="strict"` has.
- **The floor is applied at POOL ADMISSION**, on every hop, not once at the end.
  A below-floor EU is never pooled, so it cannot occupy a budget slot, cannot be
  shown to the decider, cannot drive a further hop, cannot manufacture a
  conflict, and cannot satisfy a claim under the single-EU gate.
- **The pool is authority-ordered before generation.** The same
  `select_by_authority()` reorders the pool by descending tier, so the passage
  offered to the generator leads with the strongest standing and the gate's
  first-match attribution cites the most authoritative EU that supports a claim.
- **A hop whose rows were all withheld for standing is not "no new evidence".**
  It is *"found something with no standing"* — a different fact, and the loop is
  allowed to refine and keep searching for an authority rather than halting as if
  the corpus were exhausted. (Bounded as before by `max_hops` / `max_tool_calls`
  / `timeout_s`.)
- **An empty pool caused by the floor refuses with the authority reason** and,
  as in the strict flow, **without calling the generator**.
- **The additive signals are populated identically:**
  `EvidenceSignals.authority_floor_applied` is true only when the floor
  *actually withheld* evidence during the run, and `authority_tier` reports the
  **weakest** tier among the cited EUs — a pooled answer rests on all of them, so
  reporting the strongest would overstate its standing.
- **TrustMode coupling identical to strict:** `strict` = floor-or-drop; `normal`
  = reorder/tie-break only, nothing withheld; `exploratory` = authority ignored
  entirely.
- **`search_evidence` carries `authority_meta`** on its rows (one additive key)
  so the loop can see standing at all. It is opaque metadata, not citable text —
  navigate-not-cite is untouched.
- **Not touched:** `answer/verify.py`, `is_supported_v2`, `split_claims`, the
  per-claim single-EU gate, conflict detection, and the strict flow's behaviour.
  Authority remains a selection / minimum-bar signal applied strictly *after*
  the evidence exists, never an input to the faithfulness predicate (ADR-0004).

Backward compatibility is provable and identical to the strict-flow argument:
with no `authority` metadata and no `minimum_tier`, the policy is `default.v1`,
every tier is rank 0, admission withholds nothing, the reorder is a stable no-op,
and every deep-ask Result is unchanged.

## Capabilities

### New Capabilities
- `agentic-answer`: the deep-ask loop gains authority — pool admission is
  authority-gated, the pool is authority-ordered, withheld-only hops are
  distinguishable from exhausted ones, and the authority signals are populated.

## Impact

- **Code:** `python/src/citenexus/answer/agentic.py` (policy, admission gate,
  ordering, signals, refusal reason), `python/src/citenexus/answer/authority.py`
  (the one selection point becomes generic over "anything carrying
  `authority_meta`" so the loop reuses it rather than growing a second one),
  `python/src/citenexus/tools.py` (one additive row key),
  `python/src/citenexus/client.py` (pass the existing policy through).
- **Behavioural:** with a floor configured, `strategy="deep"` answers **less**.
  That is the intended trade — stronger abstention cannot admit an ungrounded
  claim.
- **Not touched:** the faithfulness gate, the conformance fixtures, the pinned
  cross-port algorithms, and all non-Python ports.
