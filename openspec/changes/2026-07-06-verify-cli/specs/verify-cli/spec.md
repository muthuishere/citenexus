## ADDED Requirements

### Requirement: CLI verifies claims from inline JSON, with no running instance

`citenexus verify <input.json>` SHALL read a verify-input document — a
`claims` array, each with a `text` and one or more `citations` (each an inline
`passage` string) — and, for each claim, accept it as supported when the
existing `is_supported(claim.text, citation.passage)` gate returns true for
*any* of its citations. No S3 access, no LLM call, no running `CiteNexus`
instance is required.

#### Scenario: All claims grounded
- **GIVEN** a verify-input.json where every claim's text is a token subset of at least one of its cited passages
- **WHEN** the caller runs `citenexus verify input.json`
- **THEN** the process exits `0` and the report's `overall` is `"pass"`

#### Scenario: An ungrounded claim is reported with missing tokens
- **GIVEN** a claim whose text contains a token absent from every one of its cited passages
- **WHEN** the caller runs `citenexus verify input.json --format json`
- **THEN** the process exits `1`
- **AND** the claim's report entry lists `missing_tokens` — the tokens present in the claim but absent from its best-matching citation

#### Scenario: Malformed input exits distinctly from an ungrounded verdict
- **GIVEN** an input file that is not valid verify-input JSON
- **WHEN** the caller runs `citenexus verify`
- **THEN** the process exits `2` without invoking the gate

#### Scenario: Multi-claim answers are supported regardless of internal ask() limits
- **GIVEN** a verify-input.json with more than one claim, each with its own citations
- **WHEN** the caller runs `citenexus verify`
- **THEN** every claim is verified independently and appears in the report

### Requirement: The CLI's gate never drifts from the internal answer flow's gate

The CLI SHALL call `citenexus.answer.verify.is_supported` and
`has_relevance_overlap` directly — the same functions `AnswerFlow.ask()` calls —
never a reimplementation or a copy.

#### Scenario: CLI and internal ask() agree on identical input
- **GIVEN** a passage and a claim used both as an `AnswerFlow.ask()` fixture and as a verify-cli input
- **WHEN** both paths evaluate the same (claim, passage) pair
- **THEN** the CLI's per-claim verdict matches `AnswerFlow.ask()`'s faithfulness-gate outcome

### Requirement: Verification proves claim-in-passage containment, not passage authenticity

The verify report SHALL NOT claim to prove that a cited passage was extracted
from a named source document. When a citation supplies an optional
`source_checksum`, the CLI SHALL additionally report whether the checksum was
supplied and (if a manifest is given) verified, but the pass/fail verdict for
a claim SHALL be based solely on token containment against the supplied
passage text.

#### Scenario: A citation without a checksum still verifies on containment alone
- **GIVEN** a citation with only a `passage` field, no `source_checksum`
- **WHEN** the caller runs `citenexus verify`
- **THEN** the claim's verdict is based on token containment alone and the report does not assert source-document authenticity

### Requirement: Exit codes distinguish pass, fail, and malformed input for CI use

The process SHALL exit `0` when every claim is supported, `1` when at least
one claim is unsupported, and `2` when the input fails schema validation
before any gate is invoked — so a CI job can distinguish "verification ran and
failed" from "verification could not run."

#### Scenario: CI treats malformed input as a setup failure, not a verification failure
- **GIVEN** an input file missing the required `claims` field
- **WHEN** a CI job runs `citenexus verify` and checks the exit code
- **THEN** the exit code is `2`, distinct from the `1` used for a real ungrounded-claim failure
