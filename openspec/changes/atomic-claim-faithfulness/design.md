## Context

`answer/verify.py:73` proves the wrong property. `set(answer) ⊆ set(passage)` is
closed under reordering and under deletion, and both change meaning. The
`spikes/library-stress/` harness measured nine false answers accepted as grounded
9/9 in Python, Go and JS — one contract, three faithful implementations. This is
a specification defect, not implementation drift, which is why the fix is a new
predicate rather than a bug patch in one port.

Two verification paths exist today and disagree. `answer/flow.py:157` emits
`claims=(claim,)` — a single claim covering the whole answer — while
`answer/agentic.py:145` already splits claims and verifies each one. `Result` and
`EvidenceSignals` are shaped for per-claim verdicts that the strict flow cannot
produce, so `unsupported_claims_removed` is permanently 0.

`spikes/adr-0009-predicate/` prototyped the replacement and measured it. This
design follows what that spike validated; where the spike contradicted ADR-0009,
this document follows the spike.

Constraints: pure and deterministic (the conformance suite must pin it); no model
and no network on the answer path; portable to Go (RE2, no backtracking) and JS;
placement is ADR-0010 tier 1 (native per port) with the marker tables at tier 2
(canonical shared data).

## Goals / Non-Goals

**Goals:**

- Reject claims whose assertion does not follow from the cited passage, while
  keeping false rejection at or near zero on legitimately-supported answers.
- Verify per atomic claim and degrade an answer to its supported subset instead
  of discarding it whole.
- Converge the strict flow and the agentic flow on one segmenter and one
  predicate.
- Keep `is_supported` byte-identical so existing conformance vectors pass.

**Non-Goals:**

- The judge (ADR-0009 layer 2). Nothing non-deterministic enters the answer path
  in this change.
- The tokenizer and non-Latin scripts (ADR-0011). `is_supported_v2` inherits that
  gap unchanged and must not paper over it.
- The Go and JS ports. They follow once conformance vectors exist.
- Conflict surfacing (ADR-0007) and reconciliation (ADR-0008).
- Semantic entailment. The predicate stays extractive on purpose — that is what
  makes it provable offline.

## Decisions

### Ordered alignment by dynamic programming, not regex

A claim is accepted when its tokens occur in the passage **in order**, preserving
multiplicity, within a bounded interior gap. Computed as an O(|claim| × |passage|)
integer DP that returns the minimal-gap alignment span, exactly as prototyped in
`spikes/adr-0009-predicate/predicate.py:54` `align()`.

*Why over the alternatives, all three built and measured in the spike:*

- **Set containment (today):** accepts 9/9 attacks. Rejected.
- **Contiguity-only:** rejects 9/9 attacks with no table needed, but costs
  **13.3% false rejection**, concentrated entirely on answers that compress by
  dropping interior words — the most common real generator behavior. Rejected.
- **Ordered-gapped without polarity:** 0% false rejection, but **still accepts all
  three negation-deletion attacks**, because deleting `not` leaves an ordered
  subsequence. Rejected on its own, and this is precisely why the polarity guard
  is load-bearing rather than a refinement.
- **Ordered-gapped plus polarity guard:** 9/9 rejected, **0.0% false rejection
  (0/30)**. Chosen.

No regex is used at any point in the predicate — it is integer comparison over
two token arrays — so the RE2 portability question does not arise for it.

### The gap budget is pinned, not configurable

`(max_single_gap, max_total_gap)` ships at `(4, 8)`. The spike swept the budget
and found the knee at `(3, 6)`; `(4, 8)` is one notch looser to leave headroom on
compressed answers. The attacks are **insensitive to the budget** — they fail on
order, not on gap size — so loosening it trades false rejection against nothing
in attack coverage, and tightening it buys nothing.

It is pinned rather than exposed because a caller who widens it silently weakens
the guarantee, and a conformance vector cannot pin a value the caller controls.

### Polarity markers are shared data, generated into each port

Per ADR-0010 tier 2: one canonical `conformance/polarity.json`, with per-port
copies **generated**, never hand-maintained. A claim is rejected when the matched
span contains a polarity marker the claim omits.

English only at first. ADR-0007's spike measured that corrupting a polarity table
raises false abstention while recall stays flat — the failure is silent and no
internal metric degrades — so a language without a golden fixture is more
dangerous than an absent language. This is a hard rule, not a preference.

This change also exposes an existing defect it does **not** fix:
`answer/verify.py`'s `_STOPWORDS` classifies `"no"` and `"not"` as stopwords, so
`has_relevance_overlap` and `cite_check`'s coverage ratio are already blind to
negation. The polarity table must not be built by reusing that stopword set.

### Guarded segmentation, tier 1 — not Unicode segmentation

Naive `[.!?\n]+` (what ships today at `answer/agentic.py:53`) fails **54.2%**
across six languages. A guarded splitter — scanning code plus a tier-2 table of
terminators and abbreviation exceptions — drops that to **7.4%**. Japanese was
fixed by adding `。！？` to the *table*, not by changing the algorithm.

ADR-0010 requires evidence before promoting anything to tier 3, and this evidence
points the other way: the two residual failures (`"The U.S. Army"` vs
`"…at 5 p.m. She left."`, and Thai) are cases UAX #29 does not resolve either —
the standard itself calls the first a required tailoring and defers the second to
dictionary breaking. So Unicode segmentation would buy nothing here, and ADR-0009's
guess that segmentation was the portability risk was wrong.

Two RE2 findings the spike surfaced, which the implementation must respect:
`re.escape` emits `\!`, which is a **compile error** in Go RE2; and `\s` is
Unicode-aware in Python but ASCII-only in RE2. Character classes must be written
explicitly rather than escaped or abbreviated.

### Drop-not-fail, and one verification path

Unsupported claims are removed and the answer degrades to its supported subset;
zero survivors is a refusal. This is what makes `Result.claims` and
`unsupported_claims_removed` carry real values for the first time.

The strict flow adopts the agentic flow's existing `_split_claims` shape rather
than growing a second one. ADR-0009 said per-claim verification "cannot be built"
on the single-claim contract; that was wrong — `answer/agentic.py:145` already
ships it. The work is unification, and the risk is behavioral drift between the
two paths during the transition, so they must converge in one step rather than
being migrated separately.

### `is_supported` stays frozen

It remains exported and byte-identical. Existing conformance vectors keep
passing, existing indexes are unaffected, and the ports stay on v1 until their
own change lands. `is_supported_v2` is additive and versioned beside it.

## Risks / Trade-offs

- **The control set is self-authored** → 0.0% false rejection was measured
  against 30 answers written by the same agent that wrote the predicate. Before
  merge, re-measure against `examples/law-authority`, which is a live corpus with
  a real model, not synthetic fixtures.
- **The gap budget is fitted, not derived** → it was chosen from a sweep over the
  spike's own control set. Pinning it in a conformance vector makes it hard to
  change later, which is the point, but it means a wrong value is expensive.
  Re-validate on the live corpus before pinning.
- **A bad polarity table degrades silently** → measured: recall stays flat while
  false abstention rises. No internal metric catches it. Mitigation is the
  golden-fixture-per-language rule plus a deliberate table-corruption test in CI.
- **Ports diverge until their change lands** → Python rejects what Go and JS
  accept. The parity claim must be scoped to `is_supported` in the docs for the
  interim, or the polyglot promise becomes false in the other direction.
- **Trimmed answers may read oddly** → dropping an interior claim can leave prose
  that does not flow. Correct but less fluent is the right trade for this library;
  the claim list makes the trimming visible rather than hidden.
- **One existing test inverts** → `tests/cli/test_cite_check.py:89`, whose
  docstring pins the bag-of-tokens weakness as a known defect. Verified by shadow
  run: it is the only verdict change across 676 tests and 144 gate calls.

## Migration Plan

1. Land the predicate, segmenter and tables additively; nothing calls them yet.
2. Add conformance vectors for both, including the corrupted-table case.
3. Switch `answer/flow.py` to per-claim verification and converge
   `answer/agentic.py` onto the shared segmenter in the same step.
4. Invert `tests/cli/test_cite_check.py:89` with a docstring recording that the
   defect it pinned is now fixed.
5. Re-run `spikes/library-stress/stress.py` — probe A must go green for Python
   while Go and JS stay red until their change lands.
6. Re-measure on `examples/law-authority` before release.

Rollback: the change is additive up to step 3, so reverting the flow switch
restores v1 behavior exactly; `is_supported` was never modified.

## Open Questions

- Does the `(4, 8)` gap budget hold on a live corpus with a real generator, or is
  it overfitted to synthetic controls?
- Should a trimmed answer be marked as trimmed in the answer text itself, or only
  in `Result.claims`? Surfacing it in prose is more honest but changes the
  answer-language invariant's surface.
- Clause-level decomposition was not measured. Sentence-level is what ships; if
  clause-level is later needed, the tier-3 question reopens.
