# streaming-answer Specification

## Purpose

Stream answer text without weakening the verification guarantee.

## Requirements

### Requirement: Streaming wraps verified results

`CiteNexus.stream()` SHALL call the same verified answer path as `ask()` and emit
chunks only from the resulting `Result`.

#### Scenario: Strict stream is sentence-gated

- **GIVEN** strict mode
- **WHEN** the caller streams an answer
- **THEN** chunks are emitted sentence-by-sentence after verification

#### Scenario: Normal stream uses word chunks

- **GIVEN** normal or exploratory mode
- **WHEN** the caller streams an answer
- **THEN** chunks may be emitted word-by-word from the verified answer
