## MODIFIED Requirements

### Requirement: Relevance and faithfulness gates read every claimed script

The strict flow's relevance gate and faithfulness gate SHALL tokenize with the
Unicode tokenizer, not the ASCII-only frozen one. Under the frozen tokenizer both
sides of the relevance comparison were empty for every non-Latin script, so the
flow abstained before the faithfulness gate ever ran — the abstention was
over-determined and neither gate was the reason a caller was given.

#### Scenario: A supported non-Latin question is answered

- **GIVEN** a Japanese question and a Japanese passage that answers it
- **WHEN** the strict flow runs
- **THEN** the decision is `answered`
- **AND** the cited passage is the Japanese source, verbatim

#### Scenario: Frozen predicates keep their behavior

- **GIVEN** the shipped `is_supported` and `has_relevance_overlap`
- **WHEN** called on any input
- **THEN** they return exactly what they returned before this change

### Requirement: Abstention names its reason

A refusal SHALL distinguish a capability gap from an evidence judgement. Where a
script in play is not claimed, `missing_evidence` SHALL name the script and
`EvidenceSignals.unsupported_scripts` SHALL list it. Where the evidence is simply
absent, the existing evidence-absent reason SHALL be unchanged and
`unsupported_scripts` SHALL be empty.

`unsupported_scripts` SHALL be reported on answered Results too, so a caller can
see evidence the library could not read even when the answer succeeded.

#### Scenario: Capability gap is not laundered as missing evidence

- **GIVEN** a question in an unclaimed script
- **THEN** the refusal reason is the unsupported-script reason, not
  "no sufficiently relevant evidence found"

#### Scenario: Latin-script Results are unchanged

- **GIVEN** any Latin-script question and evidence
- **THEN** `unsupported_scripts` is empty and the Result is otherwise as before
