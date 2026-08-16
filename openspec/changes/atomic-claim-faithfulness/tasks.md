## 1. Canonical tables (tier 2 shared data)

- [x] 1.1 Add `conformance/polarity.json` — English polarity markers only, with a
      schema comment recording the golden-fixture-per-language rule
- [x] 1.2 Add `conformance/segmentation.json` — sentence terminators (including
      `。！？`) and the abbreviation exception set
- [x] 1.3 One canonical definition, every copy generated. NOTE: implemented in
      the OPPOSITE direction to how this task was written. The repo's established
      mechanism (`conformance/README.md`) makes the Python module the reference
      and generates `conformance/*.json` from it via `scripts/gen_conformance.py`,
      drift-guarded by `tests/test_conformance_fixtures.py` — same guarantee
      (no hand-maintained copies), opposite data flow. ADR-0010's wording assumed
      conformance/ was the source; it needs that correction.
- [x] 1.4 Confirm the polarity table does NOT reuse `answer/verify.py`'s
      `_STOPWORDS` (which wrongly classifies `no`/`not` as stopwords)

## 2. The ordered containment predicate

- [x] 2.1 Red: port the 9 adversarial fixtures from
      `spikes/library-stress/stress.py` into `python/tests/answer/` as failing
      tests against the new predicate
- [x] 2.2 Red: port the 30-answer control set from
      `spikes/adr-0009-predicate/` (verbatim, subspan, punctuation noise,
      compression) as tests asserting acceptance
- [x] 2.3 Implement `align()` in `answer/verify.py` — minimal-gap ordered
      alignment, integer DP over two token arrays, no regex, no recursion
- [x] 2.4 Implement the polarity guard over the matched span
- [x] 2.5 Implement `is_supported_v2(claim, passage)` composing 2.3 and 2.4, with
      the gap budget pinned at `(max_single_gap=4, max_total_gap=8)` and not
      exposed as a caller parameter
- [x] 2.6 Green: all 9 attacks rejected, all 30 controls accepted (0% false
      rejection)
- [x] 2.7 Add a property test asserting the predicate is strictly narrower than
      `is_supported` — anything v2 accepts, v1 accepts
- [x] 2.8 Verify `is_supported` is untouched and byte-identical

## 3. Guarded claim segmentation

- [x] 3.1 Red: tests for abbreviation (`Art. 5 applies.`), decimal
      (`500.00 milligrams`), enumeration (`(a) foo; (b) bar`), and multi-sentence
      splitting
- [x] 3.2 Implement the guarded splitter — scanning code plus the 1.2 table
- [x] 3.3 Write character classes explicitly: no `re.escape` (emits `\!`, a Go
      RE2 compile error) and no `\s` (Unicode in Python, ASCII-only in RE2)
- [x] 3.4 Assert determinism: the same answer always yields the same claims

## 4. Per-claim verification in the strict flow

- [x] 4.1 Red: test that a two-claim answer with one unsupported claim returns
      the supported claim, `unsupported_claims_removed == 1`
- [x] 4.2 Red: test that an answer with zero surviving claims refuses
- [x] 4.3 Replace the whole-answer gate call in `answer/flow.py` with segment →
      verify-each → drop-unsupported
- [x] 4.4 Populate `Result.claims` with one entry per atomic claim carrying its
      own verdict and cited span
- [x] 4.5 Populate `EvidenceSignals.unsupported_claims_removed` with the real
      count
- [x] 4.6 Confirm `Result` shape is unchanged — fields are populated, not added

## 5. Unify the two verification paths

- [x] 5.1 Point `answer/agentic.py` `_split_claims` at the shared segmenter from
      section 3, removing its local `[.!?\n]+` splitter
- [x] 5.2 Point the agentic per-claim check at `is_supported_v2`
- [x] 5.3 Assert both paths produce identical claims and verdicts for the same
      answer/passage pair
- [x] 5.4 Remove the now-duplicated segmentation code

## 6. Conformance vectors

- [x] 6.1 Add `conformance/cases/faithful_v2.json` — the 9 attacks and the 30
      controls, with expected verdicts
- [x] 6.2 Add `conformance/cases/segmentation.json` — the abbreviation, decimal,
      enumeration and multi-sentence cases
- [x] 6.3 Add a table-corruption test: deliberately corrupt `polarity.json`
      (hedges as negations, scope antonyms) and assert false abstention rises —
      pinning the silent-failure mode the ADR-0007 spike measured
- [x] 6.4 Confirm existing `conformance/cases/faithful.json` vectors still pass
      unchanged against `is_supported`

## 7. Callers and existing tests

- [x] 7.1 Update `cli/cite_check.py` to use the new predicate
- [x] 7.2 Update `cli/verify.py` to use the new predicate
- [x] 7.3 Invert `tests/cli/test_cite_check.py:89` and rewrite its docstring to
      record that the bag-of-tokens defect it pinned is now fixed
- [x] 7.4 Run the full suite — confirm 7.3 is the only verdict change across 676
      tests

## 8. Validation and documentation

- [x] 8.1 Re-run `spikes/library-stress/stress.py` — probe A green for Python
- [x] 8.2 Confirm probe A still red for Go and JS, and record that as expected
      until the ports change lands
- [ ] 8.3 Re-measure the predicate against `examples/law-authority` (live corpus,
      real model) — the design's top risk is that 0% false rejection was fitted
      to synthetic controls
- [ ] 8.4 Re-validate the `(4, 8)` gap budget on that live corpus before it is
      pinned in a conformance vector
- [x] 8.5 Scope the polyglot parity claim in the docs to `is_supported` for the
      interim, so the Python-vs-ports divergence is stated rather than hidden
- [x] 8.6 Run `task lint typecheck test`
