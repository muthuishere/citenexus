## ADDED Requirements

### Requirement: Deep-ask runs a library-scripted, bounded gather loop

The system SHALL provide an agentic answer strategy that iterates
retrieve → grade → refine, pooling **verbatim** Evidence Units across hops, under
a `LoopBudget`. The loop MUST be library-controlled — the model answers only
small single decisions, not a free tool-calling agent. It applies to any corpus.

#### Scenario: Multi-hop gather pools evidence

- **WHEN** deep-ask runs on a question needing more than one passage
- **THEN** it gathers verbatim Evidence Units across hops into a deduped pool
- **AND** the final answer is generated from that pool, not a single passage

### Requirement: The pool is answered by a per-claim, single-EU gate

Deep-ask SHALL decompose the generated answer into claims and require **each claim
to be supported by some single Evidence Unit** in the pool. It MUST NOT accept a
claim merely because its tokens appear across the **union** of pooled EUs (that
reading is strictly weaker than strict mode and admits ungrounded claims). The
per-(claim, EU) predicate reuses `is_supported`; the claim decomposition and the
single-EU quantifier are new. Any claim not supported by a single EU causes that
claim to be dropped or the answer to abstain — never emitted ungrounded.

#### Scenario: A cross-EU stitched claim is rejected

- **WHEN** an answer claim's tokens are spread across two EUs but no single EU
  supports the whole claim
- **THEN** the gate does NOT accept that claim
- **AND** the answer drops it or abstains, rather than citing the union

#### Scenario: A single-EU-supported claim is cited

- **WHEN** a claim is fully supported by one Evidence Unit
- **THEN** it is cited to that EU

### Requirement: LoopBudget bounds cost with a whole-loop wall-clock timeout

`LoopBudget` SHALL bound the loop by `max_hops`, `max_tool_calls`,
`max_evidence_units`, and a wall-clock `timeout_s`, with a `stop_when` condition
defaulting to `no_new_evidence`. `timeout_s` MUST bound the **entire** run —
including the final `generate()` and each individual tool call — not merely the
between-hops check, so a hung model call cannot exceed it. `no_new_evidence` MUST be
deterministic given a deterministic driver (a hop adding no unseen EU ends the
loop) so the loop is testable with fakes.

#### Scenario: No-new-evidence halts deterministically

- **WHEN** a hop adds no previously-unseen Evidence Unit (deterministic driver)
- **THEN** the loop stops with `stop_reason = no_new_evidence`

#### Scenario: A hung model call cannot exceed the wall-clock timeout

- **WHEN** a generate or tool call runs longer than the remaining `timeout_s`
- **THEN** it is bounded by `timeout_s` and the loop proceeds to answer from the
  pool gathered so far

### Requirement: Interrupted generation and draft claims never become grounded output

If generation is interrupted (timeout/budget mid-stream), the **partial** generated
text MUST be discarded, not gated-and-emitted. A mid-loop draft claim is
model-generated text with no source span and MUST NOT enter the evidence pool; only
retrieved verbatim Evidence Units are poolable.

#### Scenario: A partial generation is discarded

- **WHEN** generation is cut off by the wall-clock timeout
- **THEN** the partial text is discarded and the loop abstains or re-answers from
  the pool, never emitting the truncated text as a cited answer

#### Scenario: A draft claim is not poolable

- **WHEN** a mid-loop draft claim is produced for steering
- **THEN** it is used only to form the next query and never added to the evidence
  pool

### Requirement: Any exit answers through the per-claim gate

At every exit — satisfied, `no_new_evidence`, budget exhausted, or timeout — the
loop SHALL generate from the deduped verbatim-EU pool and run the per-claim
single-EU gate, then cite or abstain. A budget or timeout MUST NOT lower the
grounding bar. Budgets bound cost; only the gate bounds truth.

#### Scenario: Budget exhaustion still cites or abstains honestly

- **WHEN** the loop exits on budget with a non-empty pool
- **THEN** it generates and runs the per-claim single-EU gate
- **AND** returns a cited answer if every claim is supported by a single EU, else
  an abstain

### Requirement: stop_reason distinguishes budget-abstain from no-evidence-abstain

The result SHALL carry `signals.loop.stop_reason ∈
{no_new_evidence, sufficient, budget, timeout}`. It is metadata that explains an
abstain; it MUST NOT change the answer/abstain decision.

#### Scenario: A caller tells budget-abstain from no-evidence-abstain

- **WHEN** deep-ask abstains after exhausting the budget
- **THEN** `stop_reason` is `budget` (or `timeout`), not `no_new_evidence`

### Requirement: Mid-loop claim checks steer; the end gate guarantees

A mid-loop `check(claim)` SHALL reuse `is_supported` as a **steering** signal — an
unsupported draft claim becomes the next query. The end-of-loop per-claim single-EU
gate over verbatim EUs remains the guarantee.

#### Scenario: An unsupported draft claim drives the next hop

- **WHEN** a mid-loop draft claim is not supported by the pool
- **THEN** that gap is turned into the next retrieval query
- **AND** the final answer is still decided by the per-claim gate over verbatim EUs
