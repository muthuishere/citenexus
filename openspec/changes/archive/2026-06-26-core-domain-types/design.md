## Context

This is the first capability of CiteNexus, built foundation-first. Everything
downstream (ingest, retrieval, answer, eval) imports these models. They are pure:
no I/O, no plugins, no storage. Stack is Python ≥3.11, pydantic v2, mypy --strict,
ruff. The models must faithfully encode the v6 invariants (§7, §6b, §12, §14, §16).

## Goals / Non-Goals

**Goals:**
- A small set of immutable-by-convention, fully-typed, JSON-round-trippable models.
- Encode the hard invariants as types/validation: closed EU `type` enum, 4-number
  bbox, opaque `acl`, variable-depth partition path, structured signals (no scalar
  confidence), verbatim-passage SourceRef with additive translation.
- 100% deterministic and offline-testable.

**Non-Goals:**
- Config loading, plugin protocols, provenance *planning* (separate L1 changes).
- The `produced_by` stamp's own model lives in `provenance-and-rebuild`; here the
  Result provenance entry references it structurally (typed as a stamp/object) but
  does not define the planner.
- Any retrieval/scoring logic that *produces* signals — only the data shape.

## Decisions

- **Module layout** (one concern per file):
  - `src/citenexus/evidence/unit.py` — `EUType` (StrEnum), `Citation`, `EvidenceUnit`.
  - `src/citenexus/domain/partition.py` — `PartitionLevel` (a `(level, value)` pair)
    and `PartitionPath` (ordered tuple of levels) with `depth`, `is_prefix_of`,
    `as_pairs`, stable serialization.
  - `src/citenexus/domain/trust.py` — `TrustMode` (StrEnum: strict/normal/exploratory).
  - `src/citenexus/answer/result.py` — `EvidenceSignals`, `Decision` (StrEnum),
    `SourceRef`, `Claim`, `ProvenanceEntry`, `Result`.
- **pydantic v2 `BaseModel`** for everything, `model_config = ConfigDict(frozen=True,
  extra="forbid")` so models are hashable/immutable and typos are caught. `acl` is
  the one field typed permissively (`Any | None`) because §7c mandates it stay
  opaque — `extra="forbid"` does not apply to a declared `Any` field's contents.
- **Structured signals over scalar confidence**: `EvidenceSignals` replaces the
  removed `confidence` scalar (§12). An LLM-derived "0.87" is uncalibrated and a
  wrong number is worse than none in regulated domains; callers and strict-mode
  gates reason over the explicit signals instead.
- **Answer-language vs citation-language split** is structural: `Result.answer_language`
  is `L` (the query language); `SourceRef.passage` is verbatim in
  `passage_language`; `SourceRef.translation` is optional and additive. The type
  layer makes it impossible to "translate in place" — there is no setter that
  overwrites `passage`.
- **bbox** validated as exactly 4 numbers via a field validator.
- **PartitionPath equality/serialization**: serialize as an ordered list of
  `[level, value]` pairs (JSON-stable, language-neutral). Equality is structural on
  the ordered pairs. `is_prefix_of` compares the leading pairs.

## Risks / Trade-offs

- [Frozen models complicate incremental construction] → builders/factories in later
  layers construct in one shot; tests use full kwargs. Acceptable for value objects.
- [`acl: Any` weakens type safety] → deliberate per §7c; isolated to one field and
  documented; never parsed by the library.
- [ProvenanceEntry references a stamp defined in another change] → type it against a
  light structural shape now (a `produced_by` mapping/object); tighten to the
  concrete `ProducedBy` model when `provenance-and-rebuild` lands. Avoids a circular
  ordering dependency between the two L1 changes.

## Open Questions

- Whether `dense_vector` is stored as `list[float]` or an opaque handle on the EU —
  default to `list[float] | None` now; revisit at L4 when the LanceDB store lands.
