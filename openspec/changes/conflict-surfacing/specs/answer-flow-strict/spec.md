## ADDED Requirements

### Requirement: Conflicts are detected before generation and never resolved

The answer flow SHALL run conflict detection over the grounded candidates before
any answer is generated, and SHALL report the number of detected conflicts on
every Result it publishes — including refusals.

The flow SHALL NOT resolve a detected conflict. It SHALL NOT select a winner by
rank, recency, score or any other heuristic.

#### Scenario: Conflicting evidence is reported, not silently discarded

- **GIVEN** two retrieved passages that assert mutually exclusive facts
- **WHEN** the caller asks a question those passages answer
- **THEN** `evidence.conflicts_detected` is greater than zero

#### Scenario: An answered Result over agreeing evidence reports zero conflicts

- **GIVEN** retrieved passages that do not contradict each other
- **THEN** `evidence.conflicts_detected` is zero

### Requirement: TrustMode decides whether a conflict is answerable

An unresolved conflict whose two sides include the passage the answer cites SHALL
be treated as *touching the answer's own claim*.

- In `strict` mode the flow SHALL abstain, and the refusal SHALL cite **both**
  sides verbatim.
- In `normal` mode the flow SHALL answer and SHALL surface the conflict in
  `Result.conflicts`.
- In `exploratory` mode the flow SHALL answer and SHALL record the count only.

A conflict that does not touch the answer's own claim SHALL NOT block an answer
in any mode.

This coupling SHALL only ever increase abstention; it SHALL NOT admit any answer
that would otherwise have been refused.

#### Scenario: Strict abstains and cites both sides

- **GIVEN** two documents that disagree about the answer to the question
- **WHEN** the caller asks in `strict` mode
- **THEN** the decision is `refused`
- **AND** both passages appear in `sources`
- **AND** `Result.conflicts` describes the disagreement
- **AND** the answer asserts neither side's value

#### Scenario: Normal answers and surfaces

- **WHEN** the same question is asked in `normal` mode
- **THEN** the decision is `answered`
- **AND** `Result.conflicts` names both documents

#### Scenario: Exploratory records only

- **WHEN** the same question is asked in `exploratory` mode
- **THEN** the decision is `answered`
- **AND** `Result.conflicts` is empty
- **AND** `evidence.conflicts_detected` is greater than zero

#### Scenario: An unrelated conflict does not block the answer

- **GIVEN** a candidate pool containing a conflict between two passages the
  answer does not cite
- **WHEN** the caller asks in `strict` mode
- **THEN** the decision is `answered`
- **AND** `evidence.conflicts_detected` is greater than zero

### Requirement: Corroboration signals count evidence, not mirrors

`supporting_sources` and `distinct_documents` SHALL be computed over evidence
slots surviving near-duplicate collapse, so that the same passage stored under
several document ids is reported as one supporting source.

#### Scenario: Mirrored documents report as one

- **GIVEN** one sentence ingested under five document ids
- **WHEN** the caller asks a question it answers
- **THEN** `distinct_documents` is 1
- **AND** `supporting_sources` is 1

#### Scenario: Genuinely distinct evidence is still counted

- **GIVEN** two passages that state different facts about the same subject
- **THEN** `distinct_documents` is 2

### Requirement: The deep-ask loop carries the same guarantee

The agentic deep-ask flow SHALL apply the same detection, the same trust-mode
coupling and the same collapse over its pooled Evidence Units. A conflict touches
the answer's claim there when either side is an Evidence Unit cited by a
surviving claim.

#### Scenario: Deep-ask strict abstains on pooled contradiction

- **GIVEN** a deep-ask run whose pool contains two contradicting Evidence Units
- **AND** the answer cites one of them
- **WHEN** the caller asks in `strict` mode
- **THEN** the decision is `refused`
- **AND** both Evidence Units appear in `sources`
