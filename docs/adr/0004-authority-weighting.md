# 0004 — Authority-weighting on the grounded-evidence seam

Status: proposed · 2026-07-06

## Context

CiteNexus's faithfulness gate (`answer/verify.py:73-77`) proves an answer is
**present** in a cited passage (extractive token-subset). It does not prove the
source has the **standing** to be cited. In regulated domains a binding
appellate ruling and a random blog that merely contains the query words are
treated identically — "best data wins" today means *best-covered*, not
*most-authoritative*. That is the gap this decision closes.

The constraint is absolute: authority-weighting must not weaken the abstain
guarantee or admit any ungrounded claim (SPEC-v6 §11). Two shapes were
considered:

1. **Fold authority into grounding** — make the faithfulness gate authority-aware.
   Rejected: it entangles the two invariants, changes the byte-exact gate, and
   risks a high-authority-but-under-grounded source slipping through.
2. **Authority as a separate ranking/selection/min-bar signal over
   already-grounded evidence** — reorder grounded passages, pick which grounded
   source answers, and (strict mode) require a minimum tier or abstain. Chosen.

## Decision

Add authority-weighting on the `domain/trust.py` + `domain/partition.py` seam as
a deterministic, **metadata-derived** signal applied strictly *after* grounding:

- A pluggable, per-domain `AuthorityProfile` maps caller-supplied source
  **metadata** (never content) to a totally-ordered `AuthorityTier`. Three
  built-ins are pinned: `default.v1` (everything unranked = today's behavior),
  `legal.v1`, `medical.v1`.
- A single new selection point (`select_by_authority`, replacing
  `answer/flow.py:89`) reorders grounded candidates and enforces a strict-mode
  minimum tier. The faithfulness gate stays **byte-identical** and is never
  called by authority code.
- TrustMode coupling: strict = enforce min tier or abstain; normal = tie-break;
  exploratory = ignore.
- One additive storage column (`authority_meta`), one additive config section,
  additive Result/EvidenceSignals fields, and a cross-corpus `compare_corpora`
  comparator so `evaluate()` can rank corpus A vs B by *most-authoritative
  grounded evidence*, not coverage.
- **Backward compatibility is provable:** `default.v1` ranks every source 0, the
  selection key collapses to today's fusion order, and old corpora read
  `authority_meta=""`. Every existing Result serializes byte-for-byte unchanged;
  the feature is strictly opt-in.

Full contract, file:line integration anchors, the pinned algorithms, conformance
fixtures, TrustMode table, build plan, and risks:
**`docs/SPEC-authority-weighting-v1.md`**.

## Consequences

- The polyglot contract gains two pinned deterministic algorithms (authority
  tier + authority selection), one row-schema column, and four conformance
  fixtures — folded into SPEC-PORTS `ports-v2`. One additive column keeps it a
  minor bump; `ports-v1` readers stay correct as `default.v1`.
- Strict mode can now refuse a well-covered but low-authority source. This is
  *stronger* abstention (fewer answers, never more), so it cannot violate the
  no-ungrounded-claim / no-answer-without-evidence guarantees.
- v1 is metadata-only and deterministic. Model-derived authority classification
  and authority-aware conflict resolution (§13) are explicitly deferred — this
  ADR keeps authority a ranking/selection signal, not a reasoning engine.
- Foundation-first, additive build (ADR 0002): rungs 1–3 change no default
  behavior; the product becomes visible at rung 4; ports never block the Python
  guarantee.
