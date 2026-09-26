# 0016 — VerifyAnswer: cite-or-abstain for caller-generated answers

Status: accepted · 2026-09-24 · Go-first, confirmed by the rag_go consumer on its Dutch
goldens; **ported to Python and JS by ADR-0018** (the "Go-only" consequence
below is superseded)

All references are to `golang/` at `c7b8de9` unless stated.

## Context

`answer.AskWith` owns the whole flow: it retrieves, generates from ONE passage
(`answer/askwith.go:271`, `top := grounded[0]`) and gates every claim against
that passage. A consumer that runs its own retrieval and a writer that
synthesises across many passages cannot use it. rag_go (Go, ~50 chunks of mostly
Dutch evidence per answer, EN or NL answers) was that consumer.

rag_go also measured, offline on 235 golden answers, that the in-order token
gate alone accepted ~11% of claims in correct Dutch answers and ~1.6% in correct
English ones. On a paraphrasing writer, the extractive gate verifies QUOTES, not
claims. Anything built for this caller had to admit more than the gate does,
without letting a model decide numbers, negation or names.

## Decision

### The verb

`VerifyAnswer(ctx, answer, evidence []EvidenceUnit, opts VerifyOptions)
(result.Result, error)` (`answer/verify_answer.go:255`) is retrieval-free.
`EvidenceUnit` (`:71`) carries `ID`, `DocumentID`, `Text`, the DECLARED
`Language`, and `Authority` metadata. Failure is an error, never a refusal: bad
evidence (an empty or duplicate ID) or a checker error returns a zero Result.

### The citation contract

The writer ends each claim with `[eu:<id>]`, and may tag the part of the
question it answers with `[q:<facet-id>]` (`citationMarker`, `:149`). A marker
belongs to the claim it follows; markers are removed before the claim is
checked, so an id containing "." cannot split a sentence (`parseCitations`,
`:160`).

### Admission, in order

1. **GATE** (`:359-363`): `gate.IsSupportedV2` against a CITED unit, plus
   `clauseNegationGuard` (`answer/verify_guards.go:192`). A wrong citation is
   not rescued by another unit.
2. **QUOTE** (`:415`): the claim carries a verbatim quote of at least
   `MinQuoteTokens` = 3 tokens (`verify_guards.go:142`). The quote passes the
   gate against the cited unit, and the injected checker entails the whole
   claim. The quote anchors the content deterministically; the model vouches
   only for the words around it.
3. **MODEL** (`:444`): the checker entails the claim from a cited unit whose
   declared language differs from `AnswerLanguage`, or from any cited unit when
   `AdmitParaphrase` is set.

Steps 2–3 need the injected `contracts.SupportChecker`
(`contracts/support.go:23`, `Check(ctx, claim, passage) (entailed,
contradicted, err)`). Thresholds default to 0.9 and 0.5 (`:129-130`).

### What the model cannot override

Every model or quote admission must pass the deterministic guards
(`guards`, `verify_guards.go:124`):

- `numberGuard` (`:26`): numbers compared by ADR-0015 key, each side read in its
  own declared language;
- `negationGuard` (`:46`);
- `clauseNegationGuard` (`:192`);
- `nameGuard` (`:108`).

Contradiction ≥ threshold is a VETO even on a gate admission (`:380-388`). Every
rule after admission can only remove claims.

### Authority and conflicts

`authority.Ordered(...).WithKey(...)` (`authority/authority.go:66,81`) and
`Select` (`:141`) are the Go port of ADR-0004's strict selection. Conflicts are
detected between each supporting unit and every other selected unit
(`DetectConflictWithLanguages`, `verify_answer.go:487`). A conflict with a more
authoritative unit drops the claim; an equal-tier conflict is unresolved.
Effects are applied PER CLAIM: a `value` conflict spares a claim verified on its
own words that carries none of the differing digit runs (`spared`, `:738`;
`differingDigitRuns`, `:710`). A model paraphrase is never spared. The conflict
is reported either way.

### Partial answers

If a claim was dropped, or a declared `Facet` (`:121`) has no verified claim,
the Decision is `partial` (`:674`). Each dropped claim and uncovered facet is
named in `MissingEvidence`, and in `Evidence.MissingFacets` (`:696`).

### Wire additions

All are `omitempty`, so existing Results serialize byte-identically:
`Claim.VerifiedBy`, `Claim.Reason` (`result/result.go:127-128`),
`EvidenceSignals.ModelVerifiedClaims`, `EvidenceSignals.MissingFacets`
(`:85,89`).

## Consequences

- **Measured by the consumer**, not by this repo; single live runs, same caveat
  as the law benchmark:
  - Dutch `quote_revise` arm: 60/63 fully correct, level with the checker-off
    arm.
  - 0 citenexus misfires across the targeted re-runs (G-S4, R-103, G-D3, R-123,
    R-126, R-113, R-114, 2× each).
  - Quote-mode cited-claim pass rose 46% → 77% after the alignment fix.
- **Pinned here:** `golang/answer/testdata/verify_answer.json`, language-neutral
  vectors with must-refuse controls — Go-owned until a Python reference exists,
  then promoted to `conformance/cases/`. Run by
  `answer/verify_answer_conformance_test.go`.
- **Go-only.** Python and JS have no `VerifyAnswer` and no `SupportChecker`.
  Python has its own authority selection (`python/src/citenexus/answer/authority.py`,
  `select_by_authority`, the reference `authority.Select` ports); JS has none.
  The vectors are written so a port inherits them. Porting is deferred until
  another consumer needs it.
- **`partial` diverges from `AskWith`.** Strict `AskWith` never returns
  `partial`; this verb does, deliberately, because a multi-claim answer written
  by the caller is exactly where incompleteness must be named.
- **`clauseNegationGuard` lives only here.** The shared ADR-0009 predicate still
  accepts a claim that drops a clause-final "niet". Callers must use
  `VerifyAnswer`, not `gate.IsSupportedV2`, to get that refusal.
- **`AdmitParaphrase` trades the gate's guarantee for the model's.** It is off by
  default. An English claim over Dutch evidence depends on the injected checker
  entirely (behind the guards); that arm is still being measured by the
  consumer.
- **Related fixes on the same branch**, all ports, each with shared vectors:
  - `6f7cee0`: ADR-0015 (inclusion rule, locale-aware numbers);
  - `048a4ad`: windowed alignment DP — the gate had rejected verbatim claims
    whose first token recurs earlier in the passage;
  - `a763f8e`: segmentation of abbreviations behind an opening bracket, and
    dotted e.g./i.e.;
  - `9a7784d`: Dutch polarity, conflict and segmentation tables.
