## Why

CiteNexus is built foundation-first: every later layer (ingest, retrieval, answer,
eval) imports a shared vocabulary of typed domain objects. Before any I/O or
plugin exists we need those objects fixed and exhaustively tested, because they
encode the system's hard invariants — bbox-cited evidence, structured (not
scalar) confidence, a verbatim-citation/answer-language split, and a
variable-depth physical partition path. Getting these wrong propagates everywhere.

## What Changes

- Add the **Evidence Unit (EU)** model — the atomic retrievable object (§7): typed
  content + per-passage `Citation` (page + bbox + verbatim passage), language,
  partition path, opaque carried `acl`, dense/sparse vectors, checksums.
- Add the EU `type` enum (paragraph … community_summary).
- Add **PartitionPath** (§6b): an ordered list of named `(level, value)` pairs of
  **any depth** (not a fixed triple), with prefix addressing and stable
  serialization/equality.
- Add **EvidenceSignals** (§12): structured retrieval/verification signals that
  **replace the scalar `confidence`** (uncalibrated scalars are worse than none in
  legal/medical contexts).
- Add the **Result** object (§16): answer + `answer_language`, mode, evidence
  signals, per-claim support, `SourceRef`s (verbatim passage in source language +
  optional marked translation), missing evidence, conflicts, and a reproducible
  provenance chain.
- Add the **TrustMode** enum (§14): strict / normal / exploratory.

No configuration loading, no plugins, no storage I/O — pure pydantic v2 models.

## Capabilities

### New Capabilities
- `core-domain-types`: the shared, I/O-free domain models (EvidenceUnit,
  PartitionPath, Result + SourceRef + EvidenceSignals + ProvenanceEntry, TrustMode)
  that every other CiteNexus layer depends on.

### Modified Capabilities
<!-- none — this is the first capability -->

## Impact

- New modules: `src/citenexus/evidence/unit.py`, `src/citenexus/domain/partition.py`,
  `src/citenexus/domain/trust.py`, `src/citenexus/answer/result.py`.
- New dependency already present: `pydantic>=2.7`.
- Downstream: ingest/retrieve/answer/eval will import these; their specs assume
  this vocabulary. No runtime systems affected yet.
