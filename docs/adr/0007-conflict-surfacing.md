# 0007 — Conflict surfacing over grounded evidence

Status: proposed · 2026-08-11

## Context

`Result` already declares the shape of this feature and nothing fills it:

- `answer/result.py:66` — `EvidenceSignals.conflicts_detected: int = 0`
- `answer/result.py:131` — `Result.conflicts: tuple[str, ...] = ()`

Grep across the whole Python package returns those two declarations and **no
producer**. SPEC-v6 §11 lists "conflict surfacing" as part of `answer-flow-strict`;
the contract shipped, the logic never did. Every published `Result` therefore
asserts `conflicts_detected=0` — not "we found none", but "we never looked". For
a library whose entire promise is *answers you can defend*, silently asserting
zero conflicts is worse than omitting the field.

The failure mode is concrete and domain-general. When two retrieved passages
make opposite assertions about the same subject — an amended clause and its
superseded predecessor, two jurisdictions, a corrected figure and the original —
`answer/flow.py` walks ranked candidates and answers from the **first one that
passes `is_supported()`**. Rank order decides which of two contradictory truths
the caller sees, and the caller is told nothing happened. A near-tie in fusion
score silently flips the answer between runs of different corpora.

**Measured, 2026-08-11** (`spikes/library-stress/`, probes B and C). Two
documents asserting mutually exclusive facts, in three unrelated domains: in
every case `decision=answered`, one side cited, the other silently discarded,
`conflicts_detected=0`, `conflicts=()`. Separately, one sentence ingested under
five document IDs reports `distinct_documents=5` and `supporting_sources=5`
against exactly one independent fact — so the signal a caller uses to judge
corroboration counts mirrors as confirmations.

This is not the same problem as authority (ADR-0004). Authority asks *which
source has standing*; conflict asks *do these grounded sources disagree at all*.
Authority can only resolve a conflict once something has detected one, and in
plenty of corpora both sides carry equal authority, where the correct output is
to surface both rather than pick.

Three shapes were considered:

1. **Model-judged contradiction** — ask an LLM whether two passages conflict.
   Rejected as the v1 default: non-deterministic, un-pinnable by the conformance
   suite, and it puts a model in the path of a guarantee. Kept as an optional
   later escalation behind the ADR-0009 judge seam.
2. **Resolve the conflict** — pick a winner by recency, authority, or score.
   Rejected: resolution is a policy decision that belongs to the caller and to
   ADR-0004. A library that silently picks is exactly today's bug with more
   machinery.
3. **Detect and surface, never resolve** — deterministic detection over
   already-grounded candidates; report both sides; let TrustMode decide whether
   an unresolved conflict is answerable. Chosen.

## Decision

Add deterministic **conflict detection as a signal over grounded evidence**,
computed after retrieval and before generation, that reports and never resolves.

- A pure `answer/conflict.py` scores candidate **pairs** from the same
  post-fusion top-k for *contradiction*, using deterministic, content-derived
  signals only: high content-token overlap (same subject) combined with a
  polarity or value divergence (negation-marker asymmetry, mismatched
  numeric/date literals on an otherwise-shared token set). No model, no network.
  The polarity marker set is per-language and lives beside the existing
  `tokenize` / stopword tables so the Go and JS ports can pin it byte-for-byte.
- Detected pairs populate `conflicts_detected` and `conflicts` — the fields that
  already exist. No new public type; the Result shape is unchanged, so this is
  purely additive to serialization.
- **TrustMode coupling.** `strict`: an unresolved conflict touching the answer's
  own claim is an abstain with both sides cited — the honest output is "these
  sources disagree", not a coin flip. `normal`: answer, but surface the conflict.
  `exploratory`: record only. This can only ever produce *more* abstention in
  strict mode, so it cannot admit an ungrounded claim.
- Detection runs on grounded candidates only, and never touches
  `answer/verify.py`. The faithfulness gate stays byte-identical.
- **Near-duplicate suppression is the same seam, inverted.** The pairwise
  comparison that finds "same subject, opposite polarity" also finds "same
  subject, same polarity, ~identical text" — clones ingested under different
  document IDs. Those collapse to one evidence slot before `distinct_documents`
  is counted, so the signal stops over-reporting corroboration it doesn't have.

## Consequences

- `distinct_documents` becomes truthful. Today N copies of one passage under N
  document IDs report as N independent corroborating sources; after this they
  report as one.
- Strict mode refuses in a case where it previously answered. That is stronger
  abstention, never weaker, and it is the whole point: a defensible "these
  disagree, here are both" beats an indefensible confident pick.
- Two new pinned deterministic algorithms (pair conflict score, near-duplicate
  collapse) join the polyglot contract and need conformance fixtures per
  ADR-0006. Pairwise comparison is O(k²) over the post-rerank top-k — k is 5–7,
  so cost is negligible.
- The per-language polarity marker table is the real risk: it is a linguistic
  asset, and a bad Dutch or Tamil table produces false conflicts, which in strict
  mode means false abstention. Mitigated by starting narrow (numeric/date
  divergence, which is language-independent, plus English negation) and requiring
  a golden fixture per language before that language's markers ship.
- **Explicitly out of scope:** resolving conflicts, cross-corpus contradiction
  (only same-query candidates are compared), and model-judged semantic
  contradiction. Each is a later change.
