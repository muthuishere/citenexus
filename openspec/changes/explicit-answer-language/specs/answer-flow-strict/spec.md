## ADDED Requirements

### Requirement: A refusal reason names the cause that actually applies

The strict flow SHALL attribute a refusal to the cause that actually produced it.
A script-capability gap SHALL be named as the reason only when it genuinely
explains the refusal.

- When the QUESTION is written in a script the tokenizer does not claim, the
  reason SHALL name the unsupported script.
- When EVERY candidate was excluded because of its script, the reason SHALL say
  that no readable evidence was found and name those scripts.
- When some of the pool was readable and none of it was relevant, the reason
  SHALL be the evidence-absent reason.
- When generation failed the faithfulness gate, the reason SHALL name the gate,
  regardless of any script gap elsewhere in the pool.

`missing_evidence[0]` SHALL be that one reason. A capability note about material
that was present but unreadable MAY follow it as a further entry, and SHALL NEVER
replace it.

`EvidenceSignals.unsupported_scripts` SHALL continue to report the full observed
gap in every case; only the reason string is narrowed.

#### Scenario: An English refusal over an English pool blames the evidence

- **GIVEN** a readable English question and readable English candidates that are
  not relevant to it
- **WHEN** the question is asked
- **THEN** the refusal reason is the evidence-absent reason
- **AND** it does not mention an unsupported script

#### Scenario: An unreadable passage in the pool does not rewrite an unrelated refusal

- **GIVEN** a readable English question, readable English candidates that are not
  relevant, and one candidate in a script the tokenizer does not claim
- **WHEN** the question is asked
- **THEN** the refusal reason is the evidence-absent reason
- **AND** the unclaimed script is reported in a FURTHER `missing_evidence` entry
- **AND** `evidence.unsupported_scripts` still reports the unclaimed script

#### Scenario: A refusal caused by the script gap says so

- **GIVEN** a readable question and candidates that are ALL in a script the
  tokenizer does not claim (nothing in the pool is readable)
- **WHEN** the question is asked
- **THEN** the refusal reason states that no readable evidence was found and
  names the unclaimed script

#### Scenario: A gate failure is blamed on the gate

- **GIVEN** relevant readable candidates, a generator whose output no claim of
  which the passage supports, and an unreadable candidate elsewhere in the pool
- **WHEN** the question is asked
- **THEN** the refusal reason names the faithfulness gate

### Requirement: Unreachable material is surfaced on an answered Result

When the flow answers a question while candidate documents in the pool were
excluded because their script is not claimed, the Result SHALL make that legible
rather than silent. `evidence.unsupported_scripts` SHALL carry the unclaimed
scripts, and `missing_evidence` SHALL carry one line naming the excluded
documents and their scripts.

This is a CAPABILITY signal, never an evidence judgement. The flow SHALL NOT
downgrade an otherwise valid, grounded, cited answer to a refusal on account of
it, and SHALL NOT assert anything about the content of a passage it cannot read.

A Result over a corpus with no unclaimed script SHALL be unchanged: the signal is
empty and `missing_evidence` stays empty.

#### Scenario: An answer alongside unreadable material reports it

- **GIVEN** a relevant readable English candidate and an unreadable candidate from
  a different document
- **WHEN** the question is asked
- **THEN** the Result is answered and cites the readable passage verbatim
- **AND** `evidence.unsupported_scripts` names the unclaimed script
- **AND** `missing_evidence` names the excluded document

#### Scenario: The unreadable passage is never cited

- **GIVEN** the same pool
- **WHEN** the question is asked
- **THEN** no `SourceRef` carries the unreadable passage

#### Scenario: A fully readable corpus is unchanged

- **GIVEN** only readable candidates
- **WHEN** the question is asked
- **THEN** `evidence.unsupported_scripts` is empty
- **AND** `missing_evidence` is empty

## MODIFIED Requirements

### Requirement: Public client answers only from verified evidence

The public `CiteNexus.ask()` SHALL answer only from retrieved, verified evidence,
citing the passage it used, and SHALL refuse when no candidate supports an
answer. The Result's `answer_language` SHALL be the caller's explicit
`answer_language` when given, the question's detected language when the caller
passes `"auto"`, and otherwise the configured default answer language. It SHALL
NOT be derived from the languages of the retrieved evidence.

Cited passages SHALL remain verbatim in their own source language regardless of
the answer language.

#### Scenario: The answer language does not follow the evidence

- **GIVEN** an English question whose retrieved candidates are Telugu-dominant
- **WHEN** the question is asked with no `answer_language`
- **THEN** the Result's `answer_language` is the configured default, not `te`

#### Scenario: Citations stay in their source language

- **GIVEN** a Tamil source passage and `answer_language="en"`
- **WHEN** the question is asked
- **THEN** the cited passage is the Tamil text, verbatim and untranslated
