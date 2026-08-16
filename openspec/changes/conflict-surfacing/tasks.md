## 1. Tables (tier-2 shared data)

- [x] 1.1 Derive `CONFLICT_NEGATIONS` from the existing `POLARITY_MARKERS` in
      `answer/tables.py` minus the four scope restrictors — one polarity asset,
      used twice, so the two features cannot drift
- [x] 1.2 Add `CONFLICT_ANTONYMS`, kept closed and boring; record the measurement
      that four plausible-looking additions cost 7pp of false abstention
- [x] 1.3 Add `CONFLICT_REPORT_BIGRAMS` as **bigrams**, not unigrams
- [x] 1.4 Add `CONFLICT_SCOPE_MARKERS` and `MEASUREMENT_UNITS`; document that the
      scope list is currently inert and is not credited with the measured rate
- [x] 1.5 Record the golden-fixture-per-language rule and the reason it is
      load-bearing (a bad table raises false abstention with flat recall — the
      failure is silent)

## 2. The detector

- [x] 2.1 Red: port all 91 spike fixtures (27 true / 27 hard-negative / 22
      unrelated) plus the 15 held-out fixtures into
      `python/tests/answer/test_conflict.py`
- [x] 2.2 Implement `detect_conflict` in a new `answer/conflict.py`: subject
      overlap, `MAX_SYMDIFF`, scope guard, reported-speech guard, then the three
      rules
- [x] 2.3 Pin `MAX_RESIDUAL = 1` as a module constant, not a parameter
- [x] 2.4 Implement the measurement-vs-identifier tokenization rule with the
      letter-boundary check in code so the pattern stays RE2-clean
- [x] 2.5 Green: 0 false conflicts on hard negatives, unrelated, and held-out
      negatives; recall reported, not optimised
- [x] 2.6 Symmetry and purity tests

## 3. Near-duplicate collapse

- [x] 3.1 Red: the nine duplicate cases, including the two that must NOT collapse
      (value change, negation insertion) and the paraphrase recorded as a known
      miss
- [x] 3.2 Implement `is_near_duplicate` — conflict checked FIRST, then exact
      token-sequence equality, then Jaccard at equal length / numbers / parity
- [x] 3.3 Implement `collapse_near_duplicates` preserving rank order
- [x] 3.4 Test that a conflicting pair is never collapsed

## 4. Flow integration

- [x] 4.1 Detect conflicts over the grounded top-k before generation
- [x] 4.2 Populate `EvidenceSignals.conflicts_detected` on answered Results and
      on the gate-failure refusal — reporting 0 when nothing was checked is the
      defect being fixed
- [x] 4.3 Compute `supporting_sources` / `distinct_documents` over collapsed slots
- [x] 4.4 Strict: abstain when a conflict touches the answer's own claim, citing
      **both** sides verbatim
- [x] 4.5 Normal: answer and surface; exploratory: record the count only
- [x] 4.6 Same treatment on the deep-ask loop (`answer/agentic.py`), where the
      claim is touched if either side is a cited Evidence Unit
- [x] 4.7 Verify `answer/result.py` is untouched (the fields already exist) and
      `answer/verify.py` is byte-identical

## 5. Conformance

- [x] 5.1 Add `conformance/conflict.json` — tables plus the pinned thresholds,
      with `max_residual` published as data
- [x] 5.2 Add `conformance/cases/conflict.json` — every fixture with its verdict,
      hard negatives included, plus the identifier-tokenization vector
- [x] 5.3 Register both in `generate()` and regenerate; drift-guarded by
      `tests/test_conformance_fixtures.py`

## 6. Gates

- [x] 6.1 `uv run pytest -q` green (917 passed / 37 skipped; +119 added, none
      changed)
- [x] 6.2 `uv run mypy src` — no issues found
- [x] 6.3 `uv run ruff check` clean on every touched file
- [x] 6.4 `spikes/library-stress/stress.py` probes B and C PASS

## 7. Follow-ups (not this change)

- [ ] 7.1 Re-measure recall against `examples/law-authority`: real Evidence Units
      are multi-clause, where the residual guard fires far less often
- [ ] 7.2 Go / JS / Rust ports from the conformance vectors
- [ ] 7.3 CI reporting of the hard-negative false-conflict rate as a first-class
      number
- [ ] 7.4 Provenance-level duplicate detection (ADR-0008 lineage), which is the
      honest fix for evidential independence
