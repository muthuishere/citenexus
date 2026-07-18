## Why

Today `ask()` answers from a **single** passage (`answer/flow.py:89` — `grounded[0]`):
one retrieve, one generate, one gate. That is right for simple lookups and wrong
for questions that need to *gather* — multi-hop, cross-document, "think then
answer." The user wants a **deep-ask** mode: iterate — retrieve, judge, refine,
gather with tools — under a hard budget including a **maximum wall-clock timeout**,
then answer from everything gathered. This applies to every corpus (docs, code,
schema), not just one.

Two constraints shape the design. First, the drivers are 7B-class
(qwen2.5): prior art shows free ReAct loops collapse on them (~68% omission
failures, coherence gone after 2–3 steps; Search-R1 at 4 turns *beat* 32). So the
**library** must script the loop and let the model answer only small, single
decisions. Second, cite-or-abstain must hold unchanged: **budgets bound cost; only
the gate bounds truth.** There is no wall-clock timeout anywhere in the codebase
today — this change introduces one.

## What Changes

- **New: an agentic deep-ask answer strategy.** A library-scripted loop —
  retrieve → grade → refine → repeat, gathering with the existing agent tools —
  that pools verbatim EvidenceUnits across hops, then produces one grounded answer.
  Not a free ReAct agent.
- **New: a per-claim, single-EU grounding gate (net-new — the existing gate does
  NOT do this).** Today's gate is whole-answer token-subset against **one** passage
  (`verify.py`). Over a multi-EU pool the naive `answer ⊆ union(all EUs)` reading is
  **strictly weaker** — it would pass a claim stitched from EUs that never
  co-occurred (an ungrounded claim). Deep-ask therefore decomposes the answer into
  claims and requires **each claim ⊆ some single EU** (never the union). This
  claim-decomposition is new work, built and tested here; it is the guarantee, not
  a reuse of the strict gate.
- **New: `LoopBudget`** — `max_hops`, `max_tool_calls`, `max_evidence_units`, and a
  **whole-loop wall-clock `timeout_s`** that bounds the *entire* run including the
  final `generate()` and each individual tool call (not just the between-hops
  check), so a hung model call cannot blow it. `stop_when` defaults to
  `no_new_evidence` (deterministic *given a deterministic driver* → testable with
  fakes). At budget/timeout the loop answers best-effort from the deduped pool
  through the per-claim gate — cite or abstain. If generation is interrupted
  mid-stream, the **partial** text is discarded, not gated-and-emitted.
- **New: `signals.loop.stop_reason`** — `no_new_evidence | sufficient | budget |
  timeout` — so a *budget/timeout* abstain is distinguishable from a
  *no-evidence* abstain. Mid-loop `check(claim)` reuses `is_supported` as a
  **steering** signal (an unsupported draft claim becomes the next query). A draft
  claim is model-generated text with no source span and MUST NOT enter the evidence
  pool; only retrieved verbatim EUs are poolable. The end gate remains the guarantee.
- **New: structured single-decision output (not provider tool-calling).** The loop
  needs the model to answer small structured decisions (is this relevant? what to
  search next?) — a JSON decision parsed off the **existing** completion/`answer()`
  path, NOT full OpenAI/Anthropic function-calling machinery. This keeps the loop
  genuinely library-scripted (Decision 1) and drops the large, risky tool-calling
  primitive the design argues against needing.
- **New: `strategy=` seam on `ask()`** (`"strict"` default, `"deep"` opt-in) and an
  `AgenticAnswerFlow` beside the existing `AnswerFlow`; a new `AgenticConfig`
  section; a `FakeToolLLM` in the test fakes so the loop is provable offline.
- Honors `GraphConfig.max_hops` (declared but never used) and puts
  `Decision.partial` (exists, unused) to work.

## Capabilities

### New Capabilities
- `agentic-answer`: the deep-ask scripted loop — `LoopBudget` (incl. whole-loop
  wall-clock `timeout_s`), evidence pooling across hops, the **per-claim single-EU
  gate**, `stop_reason` signal, anytime-at-budget answer through that gate,
  `strategy=` seam.
- `structured-decision`: a structured single-decision JSON output parsed off the
  existing completion path (relevance / next-query decisions) — the loop's per-step
  primitive. NOT provider function-calling.

### Modified Capabilities
- `answer-flow-strict`: `ask()` gains a `strategy=` seam selecting strict (default,
  unchanged) vs. deep; the strict single-passage flow is untouched.

## Impact

- **Code:** new `answer/agentic.py` (`AgenticAnswerFlow`, `LoopBudget`, the
  claim-decomposition + per-claim single-EU gate); a structured-decision parse on
  the existing `answer/generator.py` + `answer/anthropic.py` completion path (no
  provider tool-calling); `strategy=` on `client.ask()`; `AgenticConfig` in
  `config/schema.py`; reuse `tools.py` `build_tools`; `FakeToolLLM` in the fakes.
- **Guarantee:** strengthened, not reused. Deep answers pass a **new** per-claim
  single-EU gate (each claim ⊆ one EU, never the pooled union); drafts never enter
  the pool; `stop_reason` only *explains* an abstain, never softens it; the
  whole-loop timeout bounds every model call.
- **Scope:** Python-only (the loop is orchestration; the Rust core stays engine-
  only). Cost/latency rise with depth — bounded by `LoopBudget`, off by default.
- **0.x:** additive (`strategy="strict"` stays the default); no migration needed.
