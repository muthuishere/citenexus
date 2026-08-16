## ADDED Requirements

### Requirement: Retrieval may be issued for N language variants of one question

The retrieval engine SHALL accept additional query phrasings for a single question
— including reformulations of it in other languages — and SHALL merge every
`(retriever x query)` list through its single RRF fusion.

The reranker SHALL always score against the original question, never a
reformulation.

Fusion SHALL be independent of the order in which the per-query lists are supplied,
and a query that returns nothing SHALL NOT perturb the fused ordering.

#### Scenario: Every query variant contributes to one fusion

- **GIVEN** a question and two language reformulations of it
- **WHEN** retrieval runs with two retrievers
- **THEN** six ranked lists are produced and fused once

#### Scenario: An empty variant list is inert

- **GIVEN** one query variant that returns no candidates
- **WHEN** the lists are fused
- **THEN** the fused ordering is identical to fusing without that variant
