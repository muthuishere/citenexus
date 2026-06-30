# conversation-memory Specification

## Purpose

Store partition-scoped conversation turns and use recalled turns as retrieval
context. Memory is not evidence and must not be cited as a source.

## Requirements

### Requirement: Memory enriches follow-up retrieval

The client SHALL store turns by conversation id and use recalled turns to expand
follow-up retrieval queries.

#### Scenario: Referential follow-up uses recent context

- **GIVEN** a prior answered turn in a conversation
- **WHEN** the next question is referential
- **THEN** retrieval uses recent memory context
- **AND** citations still come only from retrieved Evidence Units
