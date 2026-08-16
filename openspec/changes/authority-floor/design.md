# Design — authority floor (minimal correct slice of ADR-0004)

## The defect in one line

`is_supported_v2(claim, passage)` proves the claim's words came from the passage.
Nothing anywhere proves the passage may speak to the question. So the passage
that is most *textually similar* wins, and a Florida statute answers a Texas
question with 100% groundedness and `all_claims_verified: True`.

## Why authority must be metadata

Two content-derived attempts were measured and rejected (see proposal.md). The
decisive datum: **a California statute's body text does not contain the word
"California".** Jurisdiction, precedential weight, publisher standing and
recency are properties *of the document*, asserted by whoever curated the
corpus — they are not recoverable from the passage. ADR-0004 makes this
normative: authority is metadata-derived, never content-derived. This design
enforces it structurally — an `AuthorityProfile` is handed a
`Mapping[str, str]` and never a `Candidate`, so it *cannot* read passage text.

## Placement: after grounding, never inside it

ADR-0004 considered and rejected folding authority into the faithfulness gate.
We keep that: `answer/verify.py` is untouched, and no authority module imports
it. The two invariants stay separable and separately testable:

```
retrieve → fuse → rerank
         → grounded = [relevance-overlap ∧ readable-script]      (unchanged)
         → select_by_authority(grounded, policy, mode)            (NEW, one point)
         → generate → per-claim faithfulness gate                 (unchanged)
```

Authority can only ever **remove** or **reorder** candidates that grounding
already admitted. It cannot promote anything grounding rejected, so it is
incapable of admitting an ungrounded claim; the only reachable behaviour change
is *more* abstention.

The selection point sits before conflict detection deliberately: a source with
no standing should not be able to manufacture a conflict that suppresses a
binding one.

## The types

```python
@dataclass(frozen=True, order=False)
class AuthorityTier:
    rank: int          # higher = more authoritative; total order on rank alone
    name: str = ""     # display/reporting only, never compared

class AuthorityProfile(Protocol):
    profile_version: str
    def tier(self, meta: Mapping[str, str]) -> AuthorityTier: ...
```

`name` is deliberately excluded from comparison: two profiles that disagree on
naming must still produce one total order, and comparing names would make the
order depend on spelling.

Two built-ins:

- **`default.v1`** — `tier(meta) = AuthorityTier(0)` for every input. This is
  the compatibility proof: all ranks equal ⇒ the stable sort is the identity ⇒
  fusion order survives ⇒ existing Results are byte-identical.
- **`ordered.v1`** — built from a caller-supplied tuple of tier names,
  least-authoritative first, read out of a configurable metadata key (default
  `authority_tier`). Rank = index in that tuple. A tier name absent from the
  ordering ranks `-1`, below every named tier, so an uncurated document can
  never sneak above the floor.

`AuthorityPolicy` binds a profile to an optional `minimum: AuthorityTier`.
`minimum is None` ⇒ no floor ⇒ selection is reorder-only in every mode.

## The selection function

```python
select_by_authority(candidates, *, policy, mode) -> AuthoritySelection
    .candidates: list[Candidate]   # reordered, possibly filtered
    .excluded: tuple[Candidate, ...]  # grounded, but withheld for standing
    .floor_applied: bool             # == bool(excluded)
```

- `exploratory` → returns the input untouched, nothing excluded.
- `normal` → stable sort by tier descending. Nothing dropped (tie-break only).
- `strict` → drop every candidate below `policy.minimum` (when set), then the
  same stable sort. An empty result is an abstain at the call site.

Python's `sorted` is stable, so equal tiers keep fusion order by construction —
no secondary key is needed and none is used (a secondary key would silently
re-rank equal-authority evidence).

## Storage: one additive column

Per ADR-0004, one string column `authority_meta` on the EU rows, holding the
caller's metadata as canonical JSON (sorted keys). Rows written before this
change have no such key; every reader uses `row.get("authority_meta")` and
decodes a missing/blank value to `{}`. So old corpora read as unranked rather
than failing — the same "absence is not failure" posture the rest of the library
takes.

The metadata is supplied per `ingest()` call, which is exactly document
granularity — the granularity authority actually has. It rides the same seam as
`acl`: opaque, carried, never parsed by the library. Unlike `acl` it *is*
persisted to the row, because selection happens at read time.

## Signals

Two additive `EvidenceSignals` fields, modelled on `unsupported_scripts`
(ADR-0011), which established the pattern that a *capability/standing* signal is
not an *evidence* judgement:

- `authority_tier: str = ""` — the cited source's tier name.
- `authority_floor_applied: bool = False` — the floor actually withheld grounded
  evidence on this call. Not "a floor was configured": a signal that is true on
  every strict call says nothing. This one means "I had evidence and declined to
  cite it for lack of standing".

Conflating "I found nothing" with "what I found has no standing" is how the
first defect stayed invisible; the refusal reason (`"no evidence at or above the
required authority tier"`) plus these fields keep them distinguishable.

## What this deliberately does not fix

An authority floor is a *source-standing* filter, not a *subject-scope* filter.
The benchmark's five-year-commercial-lease question is answered from
`01-ca-civ-1946_1-statute` — tier `controlling-statute`, the highest tier in the
corpus, and genuinely the right *authority*; it is simply about residential
periodic tenancies, not commercial fixed terms. No ordering over sources can
catch that. It needs a scope/applicability check, which is a different signal
and a separate change.

Also out of scope, per ADR-0004: model-derived authority classification,
authority-aware conflict resolution, `compare_corpora`, and the Go/JS/Rust
ports (they stay correct by reading `authority_meta` as absent ⇒ `default.v1`).
