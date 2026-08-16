# 0004 — Authority-weighting on the grounded-evidence seam

Status: accepted · 2026-07-06 · **implemented** 2026-08-16 for the strict flow
(`answer/flow.py`) and the deep-ask loop (`answer/agentic.py`) — see
`openspec/changes/authority-floor/` and `openspec/changes/deep-ask-authority/`,
and the "Implementation notes" below for the three claims implementation
falsified.

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
- A single selection **function** (`select_by_authority`, replacing
  `answer/flow.py:89`) reorders grounded candidates and enforces a strict-mode
  minimum tier. The property being protected is **one implementation**, not one
  call site: two implementations of a min-bar are two things that can drift, and
  the drifted one is the hole. The faithfulness gate stays **byte-identical** and
  is never called by authority code.
- TrustMode coupling: strict = enforce min tier or abstain; normal = tie-break;
  exploratory = ignore.
- One additive storage column (`authority_meta`), one additive config section,
  additive Result/EvidenceSignals fields (`authority_tier`,
  `authority_floor_applied`), and a cross-corpus `compare_corpora`
  comparator so `evaluate()` can rank corpus A vs B by *most-authoritative
  grounded evidence*, not coverage.
- **Backward compatibility is provable at the level of BEHAVIOUR:** `default.v1`
  ranks every source 0, the selection key collapses to today's fusion order, and
  old corpora read `authority_meta=""`. Every existing Result carries the same
  decision, the same citations and the same values on every pre-existing field;
  the feature is strictly opt-in. **Serialization is not unchanged** — the two
  additive fields appear at their empty defaults, so a serialized Result gains
  lines (measured: `conformance/cases/result_roundtrip.json` +4 lines, two
  fields × two Results, `authority_tier: ""` and
  `authority_floor_applied: false`). Byte-exactness and additive fields cannot
  both hold; additive fields is what this ADR chose, and consumers must read
  Results by field, not by byte.

Full contract, file:line integration anchors, the pinned algorithms, conformance
fixtures, TrustMode table, build plan, and risks:
**`docs/SPEC-authority-weighting-v1.md`**.

## Implementation notes (2026-08-16)

The reasoning above stands as written. Three of its *claims* were falsified by
building it; they are corrected in place above and recorded here.

### 1. `authority_tier` on a multi-source answer is the WEAKEST cited tier

The original text ("the cited source's tier") is well-defined only for the strict
flow, which cites one source. Deep-ask (`answer/agentic.py`) cites one Evidence
Unit **per claim**, so an answer can rest on several tiers at once and the phrase
has no referent. **Normative:** `authority_tier` SHALL name the **lowest-ranked
tier among the Evidence Units actually cited**. An answer's standing is the
standing of its weakest support; reporting the strongest would let one binding
citation launder a weaker co-citation. The two definitions agree wherever they
overlap — the strict flow cites one source, so its behaviour is unchanged.

This is spelled out rather than left to each port's reading on purpose. An
ambiguous rule that four languages interpret independently is how this repo got a
faithfulness gate that accepted 9 of 9 false answers identically in Python, Go and
JS. A port that read "the cited source's tier" as *strongest* would disagree
silently, and disagreement about *reported standing* is exactly the failure this
ADR exists to prevent.

### 2. "A single new selection point" was the wrong invariant to write down

There are now **three** call sites — the strict flow (between grounding and
generation), deep-ask pool admission, and deep-ask finish. What the ADR meant to
protect survives intact and is stronger than the word "point": there is **one
implementation**, `select_by_authority`, made generic over "anything carrying
`authority_meta`" (the one-member `HasAuthorityMeta` protocol) rather than
duplicated per flow. The protocol also cannot reach `text` / `passage` /
`citable_text`, so the metadata-never-content seam is structural, not a
convention. Read the Decision as "a single selection *function*".

### 3. Serialization moved; behaviour did not

"Every existing Result serializes byte-for-byte unchanged" contradicted the same
Decision's "additive Result/EvidenceSignals fields", and measurement settled it:
`conformance/cases/result_roundtrip.json` grew by **+4 lines** when
`authority_tier: ""` and `authority_floor_applied: false` were added to its two
Results. No pre-existing field changed name, type or value, and no decision
changed. The compatibility promise is therefore **behavioural**, not byte-level.

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
