# answer-flow-strict Specification

## Purpose

Expose the v0.1 public answer surface and enforce the evidence-first guarantee:
retrieval may find candidates, but `ask()` returns an answer only when a generated
claim is supported by cited evidence. Otherwise it refuses.

## Requirements

### Requirement: Public client answers only from verified evidence

`CiteNexus.ask()` SHALL retrieve candidates, generate an answer from selected
evidence, and return `Decision.refused` when no relevant candidate exists or the
generated answer fails the faithfulness gate.

#### Scenario: Relevant evidence is cited

- **GIVEN** an ingested document that contains the answer
- **WHEN** the caller asks a matching question
- **THEN** the result is answered
- **AND** the result includes at least one source and provenance entry

#### Scenario: Unsupported generation is refused

- **GIVEN** retrieved evidence
- **WHEN** the generator returns text not supported by the cited passage
- **THEN** the result is refused
- **AND** no unsupported claim is returned

### Requirement: Evaluation CSV produces aggregate metrics

`CiteNexus.evaluate(csv)` SHALL read a golden CSV with a `question` or `query`
column and return aggregate answer, refusal, groundedness, citation, and expected
support metrics.

#### Scenario: Golden CSV is evaluated

- **GIVEN** an ingested corpus and a CSV containing questions
- **WHEN** the caller evaluates the CSV
- **THEN** the report includes total, answered, refused, grounded, cited, and
  expected-support counts
