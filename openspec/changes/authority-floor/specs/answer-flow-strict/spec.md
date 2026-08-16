## MODIFIED Requirements

### Requirement: Strict-flow candidate selection

The strict answer flow SHALL select which grounded candidate answers the question
through a single selection point that applies authority after grounding and
before generation. Generation SHALL be attempted over the authority-selected
candidates in their selected order.

When authority selection leaves no candidate, the flow SHALL refuse without
calling the generator.

#### Scenario: Generation follows the authority-selected order

- **GIVEN** grounded candidates of differing authority tiers in normal or strict mode
- **WHEN** the flow generates an answer
- **THEN** the highest-tier candidate is offered to the generator first

#### Scenario: An empty selection refuses without generating

- **GIVEN** strict mode where every grounded candidate is below the floor
- **WHEN** the question is asked
- **THEN** the generator is not called
- **AND** the result is a refusal naming insufficient authority

#### Scenario: Unconfigured authority leaves the flow unchanged

- **GIVEN** the default profile and no configured minimum tier
- **WHEN** the question is asked
- **THEN** the flow behaves exactly as it did before authority selection existed
