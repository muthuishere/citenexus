## ADDED Requirements

### Requirement: Graph edges record their derivation confidence

A `GraphEdge` SHALL carry an optional `confidence` field taking one of
`extracted` (deterministic from a parse), `inferred` (name-resolved, may be
wrong), or `ambiguous` (multiple plausible resolutions). The field MUST default to
absent/`None` so existing `graph.json` artifacts and deterministic co-mention edges
keep loading unchanged. The serialized form MUST be **byte-stable across ports**:
an unset `confidence` is **omitted from the JSON** (never written as `null`).

`confidence` routes retrieval and informs consumer weighting. For **content**
questions, navigate-not-cite holds — an inferred edge only mis-routes; the answer
still cites verbatim EU text. For **topology** questions ("who calls X?") the edge
*is* the asserted fact, so a wrong `inferred` edge CAN produce a gate-passing but
misattributed answer; `confidence` therefore MUST be surfaced to the answer path so
it can be made load-bearing (down-weight / attribute / abstain on `inferred`). This
spec does not claim inferred edges "never create an ungrounded claim."

#### Scenario: Co-mention edges carry no confidence

- **WHEN** the deterministic co-mention graph is built
- **THEN** its edges have `confidence` absent/`None`

#### Scenario: An older artifact without the field still loads

- **WHEN** a `graph.json` written before this change (no `confidence` key) is
  loaded
- **THEN** it loads successfully with every edge's `confidence` as `None`

#### Scenario: A producer marks an inferred edge

- **WHEN** an injected structural producer emits a name-resolved `calls` edge
- **THEN** that edge's `confidence` is `inferred`
- **AND** an edge it derived deterministically (e.g. `contains`) is `extracted`

### Requirement: The single-ingest path does not full-rebuild every call

A single-document `ingest()` SHALL NOT trigger a full graph rebuild (the batch path
already amortizes to one rebuild via `refresh_slow_path()`). The graph MUST be
rebuilt lazily/deferred so a graph-reading `ask()` always observes a graph
consistent with all committed ingests, while a sequence of single `ingest()` calls
does not incur one full rebuild each. A full rebuild MUST remain available on demand
(via `refresh_slow_path()`).

#### Scenario: A sequence of single ingests does not full-rebuild each call

- **WHEN** N documents are ingested one-at-a-time with the graph signal on
- **THEN** the graph is not fully rebuilt N times

#### Scenario: A graph-reading ask sees a consistent graph

- **WHEN** documents are ingested and then a graph-using `ask()` runs
- **THEN** the graph it reads reflects all committed ingests
