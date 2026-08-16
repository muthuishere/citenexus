## Context

`ask()` runs one retrieve → fuse → generate from `grounded[0]` (a single passage)
→ per-claim faithfulness gate → cite or abstain (`answer/flow.py`). Multi-passage
pooling isn't done even at hop 1, so questions needing to gather across documents
under-answer. Five agent tools already exist (`tools.py:build_tools`), but the
wire clients (OpenAI-compat + Anthropic) have no tool-calling. `Decision.partial`
exists unused; `GraphConfig.max_hops=2` is declared but never honored. The Rust
core is engine-only by design, so the loop is Python orchestration.

## Goals / Non-Goals

**Goals:**
- A bounded, iterative answer path that gathers verbatim EUs across hops and
  answers from the pool, for any corpus.
- Hard cost bounds including a **wall-clock `timeout_s`** (none exists today).
- Cite-or-abstain unchanged: the same per-claim gate over verbatim EUs decides
  truth at any exit.
- Provable offline with deterministic fakes.

**Non-Goals:**
- A free ReAct agent. The library scripts the protocol; the model makes small
  single decisions.
- Moving the loop into the Rust core (it is orchestration; stays Python).
- Summarizing evidence (would break bbox/`file:line` citations — the gate needs
  verbatim EUs).
- Changing the strict default flow.

## Decisions

### 1. Library-scripted loop, not free ReAct

The library owns the control flow — retrieve → grade → refine → repeat — and asks
the model only single, well-scoped decisions (is this relevant? what to search
next?). Rationale: 7B drivers fail free tool loops (~68% omission failures,
coherence dies after 2–3 steps; Search-R1 at 4 turns beat 32). A scripted protocol
is testable, bounded, and robust on weak drivers. CRAG/LangGraph-style, not
open-ended.

### 2. `LoopBudget` with a deterministic default stop

```
LoopBudget(max_hops=4, max_tool_calls=10, max_evidence_units=40,
           timeout_s=60, stop_when="no_new_evidence")
```

`no_new_evidence` is the default because it is **deterministic given a
deterministic driver** — a hop that adds no unseen EU ends the loop, so tests with
`FakeToolLLM` are stable (in production the stop still depends on model-chosen
queries; the determinism claim is for the test contract). `timeout_s` is a
**whole-loop wall-clock** bound (new to the codebase): it bounds the *entire* run,
including the final `generate()` and each individual tool call — not just the
between-hops check — so a hung model call cannot exceed it. The loop is anytime — it
always has a best-effort pool to answer from.

### 3. Anytime-at-budget → a per-claim, single-EU gate (net-new)

At any exit (satisfied, `no_new_evidence`, budget, or timeout) the loop generates
from the deduped verbatim-EU pool and gates → cite or abstain. **Budgets bound
cost; only the gate bounds truth.**

But the strict gate (`is_supported`) is whole-answer ⊆ **one** passage. Over a pool
the naive `answer ⊆ union(all EUs)` reading is **strictly weaker** — it admits an
ungrounded claim stitched from EUs that never co-occurred (the adversarial review's
blocker). So deep-ask does NOT reuse the strict gate over the union. It **decomposes
the answer into claims** and requires **each claim ⊆ some single EU**. This
decomposition is net-new (the codebase has none) and is the core build item of the
guarantee; `is_supported` is reused only as the per-(claim, EU) predicate. A timeout
never lowers this bar, and an interrupted partial generation is **discarded**, not
gated-and-emitted.

**Alternative — reuse the strict whole-answer gate over the union:** rejected; it
silently weakens the guarantee.

### 4. `stop_reason` distinguishes budget-abstain from no-evidence-abstain

`signals.loop.stop_reason ∈ {no_new_evidence, sufficient, budget, timeout}`. A
caller can tell "I ran out of budget" from "there is no evidence" — different
follow-ups (raise the budget vs. accept the corpus can't answer). This is
metadata; it explains an abstain, never softens it.

### 5. Mid-loop `check(claim)` steers; the end gate guarantees

`check(claim)` wraps the same `is_supported`, but its role mid-loop is
**steering**: an unsupported draft claim becomes the next query. Crucially a draft
claim is model-generated text with **no source span** — it MUST NOT enter the
evidence pool; only retrieved verbatim EUs are poolable. The end-of-loop per-claim
gate over verbatim EUs is the actual guarantee.

### 6. Structured single-decision output — NOT provider tool-calling

Because the library scripts the loop (Decision 1), the model only answers small
structured decisions (is this relevant? what to search next?). That is a **JSON
decision parsed off the existing completion/`answer()` path**, not OpenAI/Anthropic
function-calling machinery. Rationale: full provider tool-calling would be a large,
risky primitive that also contradicts the scripted-loop rationale (the model must
not own control flow on a 7B driver). A `FakeToolLLM` returns canned structured
decisions deterministically for tests.

**Alternative — full provider function-calling in the wire clients:** rejected as
unneeded scope that hands control to the model the design deliberately keeps.

## Risks / Trade-offs

- **[Cost/latency grow with depth]** → `LoopBudget` (esp. `timeout_s`) bounds every
  run; deep is opt-in via `strategy="deep"`, strict stays default.
- **[Weak driver loops incoherently]** → scripted protocol + single-decision calls;
  low default `max_hops`; `no_new_evidence` halts early.
- **[A timeout mid-generation]** → budgets checked between hops, and the final
  generate+gate always runs on the pool gathered so far; a partial pool yields a
  narrower answer or an honest abstain, never an ungrounded one.
- **[Tool-calling divergence across providers]** → one seam, provider adapters
  behind it; `FakeToolLLM` pins the contract in tests.

## Migration Plan

Additive. `strategy="strict"` remains the default, so existing calls are
unchanged. New `AgenticConfig` section defaults off. No data/artifact changes.

## Open Questions

- Default `timeout_s` (60s proposed) and whether it is per-hop or whole-loop
  (lean: whole-loop wall clock).
- Which of the five existing tools the scripted loop actually drives in v1 vs.
  defers.
- Whether `strategy="deep"` should auto-raise `top_k`/pooling at hop 1 even before
  iterating.
