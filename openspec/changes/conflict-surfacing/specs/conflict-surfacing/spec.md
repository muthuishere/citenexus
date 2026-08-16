## ADDED Requirements

### Requirement: Deterministic pairwise conflict detection

The library SHALL detect, without a model and without network access, that two
grounded passages assert mutually exclusive facts about the same subject. The
detector SHALL be a pure, total function of two passages: same inputs, same
verdict, on every port.

Detection SHALL be limited to three content-derived rules — antonym inversion,
negation-marker asymmetry, and numeric/date divergence over an otherwise-shared
token set — and SHALL NOT consult any model, network resource or caller
configuration.

The detector SHALL be symmetric: swapping the two passages SHALL NOT change
whether a conflict is reported.

#### Scenario: Negation asymmetry is a conflict

- **GIVEN** the passage "Arbitration is required for contract matters"
- **AND** the passage "Arbitration is not required for contract matters"
- **THEN** a conflict is reported

#### Scenario: Divergent values on a shared subject are a conflict

- **GIVEN** the passage "The notice period is 30 days"
- **AND** the passage "The notice period is 60 days"
- **THEN** a conflict is reported

#### Scenario: Antonym inversion is a conflict

- **GIVEN** the passage "The injunction was upheld on appeal"
- **AND** the passage "The injunction was overturned on appeal"
- **THEN** a conflict is reported

#### Scenario: Detection is symmetric

- **GIVEN** any two passages
- **WHEN** the detector is run in both orders
- **THEN** both runs agree on whether a conflict exists

### Requirement: The residual guard bounds false conflicts

A conflict SHALL be reported only when, after removing the polarity signal
itself, at most **one** content token of divergence remains between the two
passages. This bound SHALL be a pinned constant, SHALL NOT be exposed as a caller
parameter, and SHALL be published in the conformance data so no port may relax
it.

Passages that differ by a further content word — a scope, a route, an
environment, a metric — SHALL NOT be reported as conflicting.

A numeric divergence SHALL be reported only when both passages carry the same
unit tokens, and SHALL NOT be reported when one passage's numbers are a subset of
the other's.

#### Scenario: Differently scoped doses do not conflict

- **GIVEN** the passage "The recommended dose for adults is 500 mg"
- **AND** the passage "The recommended dose for children is 200 mg"
- **THEN** no conflict is reported

#### Scenario: Different metrics do not conflict

- **GIVEN** the passage "The p50 latency budget is 200 ms"
- **AND** the passage "The p99 latency budget is 900 ms"
- **THEN** no conflict is reported

#### Scenario: Unit variants do not conflict

- **GIVEN** the passage "The single dose is 1 g"
- **AND** the passage "The single dose is 1000 mg"
- **THEN** no conflict is reported

#### Scenario: Elaboration does not conflict

- **GIVEN** the passage "Net income was 4.2 million"
- **AND** the passage "Net income was 4.2 million, up from 3.1 million"
- **THEN** no conflict is reported

### Requirement: Identifier tokens are not values

A token beginning with a digit SHALL be treated as a measured value. A token
beginning with a letter and containing digits SHALL be treated as an
**identifier** and SHALL remain in the content set used by the residual guard.

#### Scenario: An identifier distinguishes two passages

- **GIVEN** the passage "The p50 latency budget is 200 ms"
- **AND** the passage "The p99 latency budget is 900 ms"
- **THEN** `p50` and `p99` are content tokens
- **AND** no conflict is reported

#### Scenario: The same passages without the identifier do conflict

- **GIVEN** the passage "The latency budget is 200 ms"
- **AND** the passage "The latency budget is 900 ms"
- **THEN** a conflict is reported

### Requirement: Reported speech suppresses detection, scoped to bigrams

A negation appearing inside a reported assertion belongs to a third party and
SHALL NOT be treated as the passage's own polarity. Reported-speech markers SHALL
be matched as **bigrams** (the complementizer form), never as single tokens.

#### Scenario: Quoted negation is not a conflict

- **GIVEN** the passage "The claim that the device is not compliant was rejected"
- **AND** the passage "The device is compliant"
- **THEN** no conflict is reported

#### Scenario: A bare "claim" does not suppress detection

- **GIVEN** the passage "The claim for indemnity is valid"
- **AND** the passage "The claim for indemnity is not valid"
- **THEN** a conflict is reported

### Requirement: Conflict marker tables are shared, derived, and fixture-gated

The negation set used by conflict detection SHALL be derived from the single
canonical polarity table rather than duplicated. Scope restrictors SHALL be
excluded from it, because they restrict a claim rather than flipping it.

Marker tables SHALL ship English only. A language SHALL NOT be claimed until
hard-negative fixtures exist for that language, and a change to any marker table
SHALL ship with hard-negative fixtures and report the resulting false-conflict
rate.

#### Scenario: Scope restrictors are not negations

- **GIVEN** the passage "All employees except contractors receive the allowance"
- **AND** the passage "All employees receive the allowance"
- **THEN** no conflict is reported

### Requirement: Near-duplicate collapse of surface clones

Passages that are surface clones of one another SHALL collapse to a single
evidence slot before corroboration signals are counted. Collapse SHALL be biased
to under-collapse: it SHALL fire only on an identical token sequence, or on
near-identical passages of comparable length with equal numeric values and equal
negation parity.

Collapse SHALL NOT claim to measure evidential independence, which is a property
of provenance rather than of text.

Conflict detection SHALL run **before** collapse, so that a value or polarity
change can never be collapsed into corroboration.

#### Scenario: One sentence under many document ids is one slot

- **GIVEN** one sentence ingested under five document ids
- **WHEN** all five are retrieved
- **THEN** they collapse to one evidence slot

#### Scenario: A value change is never collapsed

- **GIVEN** two passages differing only in a numeric value
- **THEN** they do not collapse
- **AND** a conflict is reported

#### Scenario: A negation change is never collapsed

- **GIVEN** two passages differing only by an inserted negation
- **THEN** they do not collapse
- **AND** a conflict is reported

#### Scenario: An independent restatement is not collapsed

- **GIVEN** two passages stating the same fact in different words
- **THEN** they do not collapse

### Requirement: Conformance vectors for detection and collapse

The conflict tables, the pinned thresholds, and every fixture verdict SHALL be
published as conformance data. The hard-negative fixtures SHALL be included, so a
port that reproduces the detections but not the declines is detectably wrong.

#### Scenario: Thresholds are published as data

- **WHEN** the conformance fixtures are generated
- **THEN** the residual bound appears in the published thresholds

#### Scenario: Hard negatives are published with their verdicts

- **WHEN** the conformance fixtures are generated
- **THEN** every hard-negative fixture appears with `conflict: false`
