## Why

Grounding proves *where the words came from*. It does not prove the source had
any **standing** to answer. Measured 2026-08-16 on the live `examples/law-authority`
corpus (real Jina + Gemini, v0.10.0): **4 of 8 answered questions cite an
out-of-jurisdiction source.** The worst case:

> *"What is the notice period to end a month-to-month tenancy in **Texas**?"*
> → *"not less than 30 days' notice…"*, citing `06-florida-83_57-statute` —
> a **Florida** statute. `all_claims_verified: True`, groundedness 100%.

The faithfulness gate passed that answer **correctly**: the quoted words really
are verbatim in the cited passage. Nothing in the pipeline can express "that
passage is not an authority for this question", so the most textually-similar
passage wins, whatever its standing.

Two content-derived fixes were tried and are **disproven with data** — do not
retry them:

1. **Question-term relevance floor** (query terms must appear in the cited
   passage): fixes 2 failures, breaks 3. A California statute's body text does
   not contain the word "California". Jurisdiction is **metadata, not text**.
2. **Content-token coverage threshold**: the two bad answers score 0.69 and
   0.83, squarely inside the good range (0.29–1.00). No threshold separates
   them.

ADR-0004 already specified the correct shape and was never implemented:
authority is **metadata-derived, never content-derived**, and is applied
strictly **after** grounding as a separate selection / minimum-bar signal, so
the two invariants never entangle. The owner's ruling — *"we never want wrong at
all, it's okay we can say don't know"* — makes this a release blocker.

## What Changes

- **Carry authority metadata through ingest and storage.** `CiteNexus.ingest()`
  and `IngestPipeline.ingest()` accept `authority: Mapping[str, str] | None`
  (caller-supplied, opaque key/value metadata — the same posture as `acl`).
  It is persisted on the EU rows in one additive `authority_meta` column
  (ADR-0004) and carried onto every `Candidate` by every retriever. Corpora
  ingested before this change read back as empty ⇒ unranked.
- **A pluggable `AuthorityProfile`** (`domain/authority.py`) mapping that
  metadata to a totally-ordered `AuthorityTier`. Two built-ins ship:
  `default.v1` (everything rank 0 — today's behaviour exactly) and
  `ordered.v1` (a caller-supplied ordering of tier names, most-authoritative
  last). The profile reads **metadata only**; it is never given passage text.
- **A strict-mode authority floor.** `select_by_authority()` — one new
  selection point in `answer/flow.py`, applied to the already-grounded
  candidates — reorders by tier and, in `strict`, drops every candidate below
  the caller-set minimum tier. If nothing at or above the floor survives, the
  result is an **abstain**; there is no fallback to a lower-tier source.
- **TrustMode coupling** exactly per ADR-0004: `strict` = enforce the floor or
  abstain; `normal` = tie-break only (stable reorder, nothing dropped);
  `exploratory` = ignore authority entirely.
- **Additive `EvidenceSignals` fields** — `authority_tier` (the cited source's
  tier name) and `authority_floor_applied` — so a refusal for *insufficient
  authority* is distinguishable from *no evidence found*. Modelled on
  `unsupported_scripts` (ADR-0011): a capability/standing signal, never an
  evidence judgement.
- **Config:** one additive `AuthorityConfig` section (`profile`, `tier_order`,
  `minimum_tier`), plus an `authority_profile=` constructor injection point for
  a custom profile.
- **Not touched:** `answer/verify.py` and the faithfulness predicate are
  byte-identical. Authority code never calls the gate and the gate never sees a
  tier. Ports (`golang/`, `js/`, `rust/`) are out of scope for this change.

Backward compatibility is provable: with no `authority` on ingest and no
`minimum_tier` configured, the profile is `default.v1`, every tier is rank 0,
the selection is a stable no-op sort, and no candidate is ever dropped.

## Capabilities

### New Capabilities
- `authority-floor`: authority metadata on ingest/storage/candidates, the
  pluggable `AuthorityProfile` → `AuthorityTier` mapping, the post-grounding
  `select_by_authority` selection point, the strict-mode minimum-tier floor,
  and the additive authority signals.

### Modified Capabilities
- `answer-flow-strict`: the strict flow selects among grounded candidates by
  authority before generating, and abstains when no candidate meets the floor.

## Impact

- **Code:** new `python/src/citenexus/domain/authority.py`,
  new `python/src/citenexus/answer/authority.py`;
  `client.py` (ingest param + wiring), `ingest/pipeline.py` (row column),
  `retrieve/{vector,lexical,structure}.py` (carry the column),
  `retrieve/types.py` (`Candidate.authority_meta`), `answer/flow.py`
  (selection point), `answer/result.py` (two additive signals),
  `config/schema.py` (one additive section).
- **Data:** one additive `authority_meta` string column on the EU rows.
- **Behavioural:** with a floor configured, strict mode answers **less**. On the
  law benchmark 3 currently-"correct" answers that cite Florida become
  refusals. That is the intended trade: stronger abstention can never admit an
  ungrounded claim.
- **Not touched:** the faithfulness gate, conflict surfacing (ADR-0007),
  reconciliation (ADR-0008), the tokenizer (ADR-0011), and all non-Python ports.
