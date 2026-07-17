## ADDED Requirements

### Requirement: The loop drives the model via structured single decisions, not tool-calling

The deep-ask loop's per-step model primitive SHALL be a **structured single-decision
output** — a small JSON decision (e.g. relevance judgement, next-query) parsed off
the **existing** completion/`answer()` path of the OpenAI-compatible and Anthropic
generators. It MUST NOT require provider function/tool-calling machinery, and the
model MUST NOT own control flow (the library scripts the loop). Auth stays the
existing `${ENV}`-header path; no new HTTP/credential plumbing.

#### Scenario: A decision is parsed from a plain completion

- **WHEN** the loop asks the model whether a candidate is relevant
- **THEN** the model returns a structured decision parsed from a normal completion
- **AND** no provider tool/function-calling API is used

### Requirement: A deterministic decision fake exists for tests

The test fakes SHALL include a `FakeToolLLM` that returns canned structured
decisions deterministically, so the deep-ask loop is provable offline without a live
endpoint.

#### Scenario: The loop runs fully offline

- **WHEN** deep-ask runs with `FakeToolLLM` and the other deterministic fakes
- **THEN** the loop, budgets, and gate all execute with no network access
