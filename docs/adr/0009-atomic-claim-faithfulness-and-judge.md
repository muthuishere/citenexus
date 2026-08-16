# 0009 — Atomic-claim faithfulness and the judge seam

Status: proposed · 2026-08-11

## Context

The faithfulness gate is one function:

```python
# answer/verify.py:73
def is_supported(answer: str, passage: str) -> bool:
    """Every answer token must appear in the cited passage."""
    answer_tokens = set(tokenize(answer))
    passage_tokens = set(tokenize(passage))
    return bool(answer_tokens) and answer_tokens <= passage_tokens
```

This is deliberately extractive, and that choice is right: it is deterministic,
offline-provable, cheap, and pinnable byte-for-byte across the Python, Go and JS
ports by the ADR-0006 conformance vectors. It is the reason "no ungrounded claim"
is a property the test suite can prove rather than a marketing line. None of that
changes here.

But the predicate is **set containment**, and set containment is blind to two
things that carry most of the meaning in a sentence:

- **Order.** `{tenant, pays, landlord}` and `{landlord, pays, tenant}` are the
  same set. An answer that inverts the parties to a transaction is a token subset
  of the passage that states it correctly, and passes.
- **Deletion.** A subset is closed under removing tokens, and `not` is a token.
  An answer that drops the negation from a prohibition is a strict subset of the
  passage that prohibits it, and passes.

**Measured, 2026-08-11** (`spikes/library-stress/`): nine adversarial answers,
each false with respect to its passage, across five unrelated domains. Accepted
as grounded by Python `answer/verify.py:73` — 9/9. By Go `golang/gate/gate.go:75`
— 9/9. By JS `js/src/gate/gate.ts:32` — 9/9. This is not three bugs; it is one
contract that three implementations faithfully reproduce, and the existing
ADR-0006 conformance vectors currently pin it in place.

So the gate proves the answer's *vocabulary* was drawn from the cited passage. It
does not prove the answer's *assertion* follows from it. Both failure modes
produce output that is verbatim-sourced, correctly cited to a real document, page
and bbox — and false. That is a worse artifact than an ungrounded answer, because
every visible signal says it is trustworthy.

The second gap is that `flow.py:157` emits `claims=(claim,)` — a single claim per
answer, the whole answer text. Faithfulness is therefore all-or-nothing. A
two-sentence answer where one sentence is supported and one is not has no
representable state: it either passes whole or fails whole. Per-claim
verification, which SPEC-v6 §11 describes and the review of 2026-07-17 recorded
as missing, cannot be built on a single-claim contract.

The third gap is the empty socket. `plugins/base.py:103` defines `JudgePlugin`
and `config/schema.py:274` defines `JudgeConfig(enabled=False, mode="offline")`.
Neither has an implementation anywhere in the tree. `evaluate.py` scores
`groundedness_rate` / `citation_rate` / `expected_support_rate` against a golden
CSV — reference-*based*, synchronous, and therefore unable to say anything about
production traffic where no golden answer exists.

## Decision

Split verification into two layers with a hard boundary between them, and keep
the deterministic layer sovereign.

**Layer 1 — atomic-claim decomposition (deterministic, always on).**

- Decompose a generated answer into atomic claims on deterministic boundaries
  (sentence, then clause), and run the gate **per claim**. `Result.claims` carries
  one entry per atomic claim with its own verdict and its own cited span.
- Unsupported claims are **dropped, not failed** — the answer degrades to the
  supported subset, and `unsupported_claims_removed` (already in
  `EvidenceSignals`) finally reports something real. An answer with zero
  surviving claims is an abstain.
- Strengthen the predicate from set containment to **order-and-multiplicity-aware
  containment**: an atomic claim must match a contiguous or near-contiguous span
  of the cited passage, and any polarity marker present in that span must be
  present in the claim. This closes both the inversion and the negation-deletion
  holes while staying pure, deterministic, and portable. It is a strictly
  narrower predicate — everything it accepts, `is_supported` already accepted —
  so it can only reduce what gets through.
- `is_supported` itself stays exported and byte-identical for the conformance
  vectors; the new predicate is additive and versioned alongside it.

**Layer 2 — the judge (optional, advisory, never in the answer path).**

- Implement `JudgePlugin` against an injected OpenAI-compatible endpoint, per the
  no-bundled-models rule, and score **context recall**, **answer relevance** and
  **faithfulness** on sampled answers. Self-hosting is a deployment choice the
  injected-endpoint design already supports, so EU-sovereign and air-gapped
  deployments need no special path.
- The judge runs **asynchronously and out of band**. It flags to a review queue
  and writes to the audit stream. It may never gate, edit, or override an answer.
  A non-deterministic component cannot be load-bearing for a guarantee that the
  conformance suite has to prove.
- Judge verdicts are recorded next to the deterministic verdict for the same
  answer, which makes calibration measurable: how often does the judge disagree
  with a gate that is provably correct on the extractive question.

## Validation (spike, 2026-08-11 — `spikes/adr-0009-predicate/`)

The decision stands. Measured results, and three corrections to the text above.

- **The predicate works.** All 9 adversarial fixtures rejected, **0.0% false
  rejection (0/30)** on a control set of legitimately-supported answers in four
  shapes (verbatim, subspan, punctuation/case noise, interior-word compression).
  Shadow-run over the real suite (676 tests, 144 gate calls): **exactly one
  verdict changes** — `tests/cli/test_cite_check.py:89`, whose docstring already
  pins the bag-of-tokens weakness as a known defect. It inverts.
- **The polarity table is load-bearing, not a refinement.** Ordered-gapped
  containment *without* polarity has 0% false rejection but still accepts all
  three negation-deletion attacks. Contiguity-only rejects all 9 but costs 13.3%
  false rejection, concentrated on compressed answers — the most common real
  generator behavior. The formulation in this ADR beat both.
- **The predicate needs no regex at all** — integer DP over two token arrays —
  so the RE2 portability concern does not apply to it.

**Correction 1 — claim segmentation is tier 1, not a tier-3 candidate.** Naive
`[.!?\n]+` splitting fails 54.2% across six languages; a guarded splitter
(tier-1 scanning code plus a tier-2 terminator/abbreviation table) drops it to
7.4%. Japanese was fixed by adding `。！？` to a *table*, not by an algorithm, and
the two residual failures are cases UAX #29 does not fix either. ADR-0010's
evidence bar for Rust is not met here.

**Correction 2 — "cannot be built on the single-claim contract" is wrong.**
`answer/agentic.py:145` already ships `_split_claims` plus per-claim
`is_supported` on the deep-ask path. The work is to *unify and fix* two divergent
verification paths, not to build one from nothing.

**Correction 3 — the real portability risk is the tokenizer, not the segmenter.**
`citenexus/tokenize.py` is `[a-z0-9]+` over `.lower()`, so Japanese, Chinese,
Arabic and Tamil produce zero tokens, `is_supported` short-circuits on
`bool(answer_tokens)`, and a verbatim quote of its own source is rejected as
ungrounded. Every non-Latin-script answer abstains today. `is_supported_v2`
inherits this unchanged. This is out of scope here and is decided in **ADR-0011**;
it must not be bundled into this change, because it breaks a frozen cross-port
contract and forces a native-dependency decision for Go and JS.

Also surfaced and not fixed here: `answer/verify.py`'s `_STOPWORDS` classifies
`"no"` and `"not"` as stopwords, so `has_relevance_overlap` and `cite_check`'s
coverage ratio are already blind to negation.

## Consequences

- Answers get shorter and more defensible. Per-claim dropping means a partially
  supported answer returns its supported part rather than passing whole or
  failing whole.
- The stricter predicate will reject some answers that pass today. Every such
  answer is one whose assertion did not follow from its citation, so this is the
  fix, not a regression — but it is a behavioral break, and per the 0.x policy it
  ships as a versioned predicate with the old one retained.
- Two more pinned algorithms (claim decomposition, ordered containment) join the
  polyglot contract with conformance fixtures. Claim decomposition on
  non-sentence-terminated scripts is the portability risk and needs per-language
  fixtures before those languages are claimed.
- Adding a model to evaluation reintroduces non-determinism to a library that has
  worked hard to avoid it. The mitigation is architectural, not procedural: the
  judge is physically unable to affect an answer, because it never runs on the
  answer path.
- `evaluate()` gains a reference-free mode and can therefore be pointed at
  production traffic, not just a golden CSV. This is what makes continuous
  measurement possible in deployments that have no ground truth.
