## Why

Two fields ship declared and unwritten. `answer/result.py:66`
(`EvidenceSignals.conflicts_detected`) and `answer/result.py:131`
(`Result.conflicts`) have no producer anywhere in the package, so every published
Result asserts `conflicts_detected=0` — which does not mean "we found none", it
means "we never looked". For a library whose promise is *answers you can defend*,
silently asserting zero conflicts is worse than omitting the field.

The failure mode is concrete. When two retrieved passages assert opposite facts
about the same subject — an amended clause and its superseded predecessor, two
jurisdictions, a corrected figure and the original — `answer/flow.py` answers from
the first candidate that passes the faithfulness gate. **Rank order decides which
of two contradictory truths the caller sees, and the caller is told nothing
happened.**

Measured 2026-08-11 in `spikes/library-stress/`, probes B and C. Two documents
asserting mutually exclusive facts, in three unrelated domains: in every case
`decision=answered`, one side cited, the other silently discarded,
`conflicts_detected=0`, `conflicts=()`. Separately, one sentence ingested under
five document IDs reported `distinct_documents=5` and `supporting_sources=5`
against exactly one independent fact — the signal a caller uses to judge
corroboration counts mirrors as confirmations.

The design is validated, not speculative. `spikes/adr-0007-conflict/` measured a
deterministic detector over 91 fixtures in five domains at **0/27 false conflicts
on hard negatives**, 0/22 on unrelated pairs, and 0/10 on a held-out set written
after the thresholds were frozen. This change ports that design; the
implementation re-measures the same fixtures and reaches **0/27 hard-negative
false conflicts at 27/27 recall** (see design.md for the two amendments that
bought the recall).

Decision: ADR-0007 (surface, never resolve). Placement: ADR-0010 tier 1 with
tier-2 tables.

## What Changes

- Add `answer/conflict.py`: a pure pairwise contradiction test over grounded
  candidates, with three rules (antonym inversion, negation asymmetry, numeric
  divergence) and a set of guards whose whole job is to **decline**.
- Add ADR-0007 tables to `answer/tables.py`, deriving `CONFLICT_NEGATIONS` from
  the existing `POLARITY_MARKERS` so the two features cannot drift. There is one
  polarity asset, used twice.
- Populate `EvidenceSignals.conflicts_detected` and `Result.conflicts` from the
  strict flow and the deep-ask loop. **No change to the `Result` shape** — this is
  purely additive to serialization.
- **TrustMode coupling.** `strict`: an unresolved conflict touching the answer's
  own claim abstains **with both sides cited**. `normal`: answer, but surface the
  conflict. `exploratory`: record the count only. Strict can only produce *more*
  abstention, so it cannot admit an ungrounded claim.
- Add near-duplicate collapse so `distinct_documents` and `supporting_sources`
  count evidence slots rather than mirrors. It claims **surface clones only** and
  is deliberately biased to under-collapse.
- Add conformance vectors: `conformance/conflict.json` (tables + the pinned
  thresholds, `max_residual` included as data) and `conformance/cases/conflict.json`
  (every fixture with its verdict, hard negatives included).

## Capabilities

### New Capabilities
- `conflict-surfacing`: deterministic pairwise conflict detection, near-duplicate
  collapse, the conflict marker tables, and the trust-mode coupling.

### Modified Capabilities
- `answer-flow-strict`: the strict flow detects conflicts before generation,
  abstains with both sides cited when one touches the answer's claim, and reports
  corroboration signals over collapsed evidence slots.

## Impact

- **Code:** new `python/src/citenexus/answer/conflict.py`; `answer/tables.py`
  (additive tables); `answer/flow.py` and `answer/agentic.py` (detect, collapse,
  couple to TrustMode). `answer/result.py` is **untouched** — the fields already
  exist. `answer/verify.py` is untouched; the faithfulness gate stays
  byte-identical.
- **Data:** `conformance/conflict.json`, `conformance/cases/conflict.json`.
- **Behavioral (breaking in strict mode):** a question whose evidence disagrees
  now refuses where it previously answered one side. That is the point. Both
  passages are returned as sources, so the caller can resolve it themselves.
- **Signals:** `distinct_documents` and `supporting_sources` go DOWN on mirrored
  corpora. They were over-reporting.
- **Ports:** none in this change. Go/JS/Rust follow from the conformance vectors.
  Until then the polyglot parity claim excludes conflict detection.
- **Not touched:** resolving conflicts (never — that is ADR-0004 and the caller),
  cross-corpus contradiction, model-judged contradiction, `answer/verify.py`,
  storage, ingest.
