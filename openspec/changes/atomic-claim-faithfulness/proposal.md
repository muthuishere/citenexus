## Why

The faithfulness gate proves the wrong thing. `answer/verify.py:73` is
`set(answer_tokens) ⊆ set(passage_tokens)`, and set containment is closed under
two meaning-changing operations: reordering (inverting the parties to an
obligation is a token-set identity) and deletion (`not` is a token, so dropping a
negation yields a strict subset). Measured on 2026-08-11 in
`spikes/library-stress/`: nine adversarial answers, each **false** with respect
to its cited passage, across five unrelated domains — accepted as grounded 9/9 in
Python, 9/9 in Go, 9/9 in JS.

The resulting artifact is worse than an ungrounded answer: it is verbatim-sourced,
correctly cited to a real document, page and bbox, and asserts the opposite of
its source. Every visible signal says it is trustworthy. This is the only known
defect where CiteNexus returns a confidently false answer rather than a missing
signal, which makes it the highest-priority correctness work in the backlog.

Verification is also all-or-nothing. `answer/flow.py:157` emits `claims=(claim,)`
— one claim covering the whole answer — so a partly-supported answer has no
representable state and is discarded whole. `Result.claims` and
`EvidenceSignals.unsupported_claims_removed` are shaped for per-claim verdicts
the strict flow cannot produce. Meanwhile `answer/agentic.py:145` already ships
`_split_claims` plus per-claim `is_supported` on the deep-ask path, so the
library has two divergent verification paths today.

The replacement is validated. `spikes/adr-0009-predicate/` measured **9/9 attacks
rejected at 0.0% false rejection (0/30)** on legitimately-supported controls, and
a shadow run over the real suite (676 tests, 144 gate calls) changes **exactly one
verdict** — `tests/cli/test_cite_check.py:89`, whose own docstring pins the
bag-of-tokens weakness as a known defect.

Decisions: ADR-0009 (this change), ADR-0010 (placement: tier 1, native per port).

## What Changes

- Add `is_supported_v2(claim, passage)`: order- and multiplicity-aware
  containment. A claim must match an ordered, gap-bounded span of the passage,
  and any polarity marker inside that span must also appear in the claim.
  Implemented as integer dynamic programming over two token arrays — **no
  regex**, so it ports to Go (RE2) and JS unchanged.
- Add a canonical polarity-marker table at `conformance/polarity.json`
  (ADR-0010 tier 2: shared data, native code), **English only**. The spike
  measured that a corrupted table raises false abstention while recall stays
  flat — the failure is silent — so no language may be claimed without a golden
  fixture.
- Add guarded claim segmentation: tier-1 scanning code plus a tier-2
  terminator/abbreviation table. Naive `[.!?\n]+` splitting fails 54.2% across
  six languages; the guarded splitter drops that to 7.4%.
- Unify the two verification paths. `answer/agentic.py:145` `_split_claims` and
  the strict flow converge on one segmenter and one predicate.
- Per-claim **drop-not-fail**: unsupported claims are removed and the answer
  degrades to its supported subset; zero surviving claims is an abstain.
  `Result.claims` carries one entry per atomic claim with its own verdict and
  cited span, and `unsupported_claims_removed` finally reports a real count.
- `is_supported` stays exported and byte-identical so existing conformance
  vectors keep passing; `is_supported_v2` is additive and versioned beside it.
- **BREAKING (behavioral, not API):** answers whose assertion does not follow
  from their citation are now rejected or trimmed. The predicate is strictly
  narrower — everything it accepts, `is_supported` already accepted — so this can
  only reduce what passes, never admit anything new. `tests/cli/test_cite_check.py:89`
  inverts.

## Capabilities

### New Capabilities
- `atomic-claim-faithfulness`: claim segmentation, the ordered-containment
  predicate with polarity guard, the canonical polarity table, and per-claim
  drop-not-fail verification with per-claim provenance.

### Modified Capabilities
- `answer-flow-strict`: the strict flow verifies per claim instead of per answer,
  degrades to the supported subset instead of passing or failing whole, and
  populates `Result.claims` and `unsupported_claims_removed` with real values.

## Impact

- **Code:** `python/src/citenexus/answer/verify.py` (additive), `answer/flow.py`
  (verification loop), `answer/agentic.py` (converge on the shared segmenter),
  `answer/result.py` (populate existing fields — no shape change),
  `cli/cite_check.py` and `cli/verify.py` (consume the new predicate).
- **Data:** new `conformance/polarity.json` and terminator/abbreviation table;
  new conformance vectors for the predicate and the segmenter.
- **Tests:** `tests/cli/test_cite_check.py:89` inverts (documented known defect).
  No other verdict changes in 676 tests.
- **Ports:** none in this change. Go and JS follow once conformance vectors
  exist; until then the ports remain on v1 and the parity claim is scoped to
  `is_supported`.
- **Not touched:** the judge (ADR-0009 layer 2), the tokenizer and non-Latin
  scripts (ADR-0011 — `is_supported_v2` inherits that gap unchanged), conflict
  surfacing (ADR-0007), reconciliation (ADR-0008).
