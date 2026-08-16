## ADDED Requirements

### Requirement: ask() selects an answer strategy

`CiteNexus.ask()` SHALL accept a `strategy` seam selecting the answer flow:
`"strict"` (the default — the existing single-passage, gated flow, unchanged) or
`"deep"` (the agentic gather loop). The default MUST remain `"strict"` so existing
calls are unaffected; `"deep"` is opt-in. Both strategies end in the **same**
per-claim faithfulness gate over verbatim Evidence Units.

#### Scenario: Strict is the default and unchanged

- **WHEN** `ask(question)` is called with no strategy
- **THEN** it runs the strict single-passage flow exactly as before

#### Scenario: Deep opts into the gather loop

- **WHEN** `ask(question, strategy="deep")` is called
- **THEN** it runs the bounded agentic loop and returns an answer decided by the
  per-claim gate over verbatim Evidence Units
