## MODIFIED Requirements

### Requirement: Public client answers only from verified evidence

`CiteNexus.ask()` SHALL retrieve candidates, generate an answer from selected
evidence, decompose that answer into atomic claims, and verify each claim
independently against its cited passage.

`ask()` SHALL return `Decision.refused` when no relevant candidate exists, or
when no atomic claim survives verification. When some but not all claims survive,
`ask()` SHALL return an answer composed only of the surviving claims rather than
refusing the answer as a whole.

Verification SHALL use the ordered containment predicate with the polarity guard,
so that an answer whose assertion does not follow from its cited passage is
rejected even when every one of its tokens appears in that passage.

#### Scenario: Relevant evidence is cited

- **GIVEN** an ingested document that contains the answer
- **WHEN** the caller asks a matching question
- **THEN** the result is answered
- **AND** the result includes at least one source and provenance entry

#### Scenario: Unsupported generation is refused

- **GIVEN** retrieved evidence
- **WHEN** the generator returns text in which no claim is supported by the cited
  passage
- **THEN** the result is refused
- **AND** no unsupported claim is returned

#### Scenario: Reordered generation is refused

- **GIVEN** retrieved evidence stating an obligation between two parties
- **WHEN** the generator returns that obligation with the parties inverted
- **THEN** the result is refused
- **AND** no unsupported claim is returned

#### Scenario: Negation-dropping generation is refused

- **GIVEN** retrieved evidence stating a prohibition
- **WHEN** the generator returns the same statement with the negation removed
- **THEN** the result is refused

#### Scenario: Partly supported generation returns its supported claims

- **GIVEN** retrieved evidence
- **WHEN** the generator returns one supported claim and one unsupported claim
- **THEN** the result is answered
- **AND** the answer contains only the supported claim
- **AND** `EvidenceSignals.unsupported_claims_removed` reports 1

### Requirement: Evaluation CSV produces aggregate metrics

`CiteNexus.evaluate(csv_path)` SHALL read a golden CSV, ask each question, and
return aggregate groundedness, citation, and expected-support rates.

Because verification now operates per claim, an answer that returns a supported
subset SHALL be scored on the claims it actually returned.

#### Scenario: Golden CSV is scored

- **GIVEN** a golden CSV of questions and expected support
- **WHEN** the caller runs `evaluate()`
- **THEN** the report contains groundedness, citation, and expected-support rates

#### Scenario: Trimmed answers are scored on surviving claims

- **GIVEN** a golden row whose generated answer had an unsupported claim removed
- **WHEN** the row is scored
- **THEN** only the surviving claims are considered for groundedness
