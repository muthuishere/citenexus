## ADDED Requirements

### Requirement: Signal enum defines the six retrieval capabilities

The library SHALL expose a `Signal` enumeration whose members are exactly
`embedding`, `text`, `graph`, `community`, `structure`, and `wiki`. No other
members SHALL exist, and the set SHALL be the single source of truth for which
signals a client may declare.

#### Scenario: Enum membership is exactly the six signals

- **WHEN** the members of `Signal` are listed
- **THEN** they are exactly `{embedding, text, graph, community, structure, wiki}` and nothing else

#### Scenario: An unknown signal name is rejected

- **WHEN** a client is constructed with `signals=["telepathy"]`
- **THEN** construction raises a validation error naming the invalid signal

### Requirement: Default client declares all signals

When `signals` is not provided, the client SHALL behave as though every member of
`Signal` were declared, so the zero-config path builds and queries the full set.

#### Scenario: Omitting signals enables all six

- **WHEN** a client is constructed without a `signals` argument
- **THEN** the resolved signal set equals all six `Signal` members

### Requirement: Signal gate controls both ingest build and ask query

The configuration layer SHALL provide gating predicates — "does ingest build
signal X?" and "does ask query signal X?" — that return true only for declared
signals. A signal that is not declared MUST be gated OUT of both phases.

#### Scenario: embedding+text client gates out graph, community, and wiki

- **WHEN** a client is constructed with `signals=["embedding","text"]`
- **THEN** the ingest-build predicate returns false for `graph`, `community`, and `wiki`
- **AND** the ask-query predicate returns false for `graph`, `community`, and `wiki`
- **AND** both predicates return true for `embedding` and `text`

#### Scenario: A slow-path signal is enqueued only when declared

- **WHEN** the declared signals include none of `graph`, `community`, `wiki`
- **THEN** the gate reports that no slow-path build is required

### Requirement: Configuration schema parses the full §17 surface with sane defaults

The library SHALL provide a typed configuration model covering the §17 sections
(client, storage, llm, embedding, reranker, vision, vector_store, graph,
retrieval, trust, multilingual, access_control, plugins, provenance, worker,
telemetry, memory, judge, streaming). Unspecified fields SHALL take the
documented defaults.

#### Scenario: Defaults match the specification

- **WHEN** a configuration is built with only a storage bucket supplied
- **THEN** `trust.default_mode` is `strict`
- **AND** `retrieval.rrf_k` is `60` and `retrieval.top_k` is `11`
- **AND** `retrieval.lexical_signal` is `bge_m3_sparse`
- **AND** `multilingual.detect_confidence_threshold` is `0.50`
- **AND** `multilingual.answer_in_query_language` is `true`

#### Scenario: A representative §17 YAML loads without error

- **WHEN** a YAML document containing the §17 sections is loaded
- **THEN** a fully typed configuration object is returned with those values applied

### Requirement: partition_hierarchy accepts any depth and any level names

The `storage.partition_hierarchy` SHALL be an ordered list of level names of any
length ≥ 1, with no assumption of exactly three levels.

#### Scenario: Three-level and flat hierarchies both validate

- **WHEN** one config sets `partition_hierarchy: [org, product_line, product]` and another sets `partition_hierarchy: [workspace]`
- **THEN** both configurations are valid
- **AND** a four-level `[firm, practice, client, matter]` hierarchy is also valid

### Requirement: Configuration loads from dict, YAML, or environment with defined precedence

The loader SHALL accept a Python dict, a YAML file path, or environment overrides,
and SHALL apply them with a defined, deterministic precedence (later sources
override earlier ones), exposed as a `from_config(...)` entry point.

#### Scenario: Environment override wins over file value

- **WHEN** a YAML file sets `trust.default_mode: normal` and an environment override sets it to `strict`
- **THEN** the resolved configuration reports `trust.default_mode` as `strict`

### Requirement: Validation against citenexus.validate.yaml warns and never errors

When a `citenexus.validate.yaml` allow-list is supplied, the library SHALL compare
the live client's declared `signals` (and doc types) against `allowed_signals`
(and `allowed_doc_types`) and SHALL emit a warning on divergence while proceeding.
It MUST NOT raise. When no validation file is supplied, no check SHALL run.

#### Scenario: Declaring a disallowed signal warns but proceeds

- **WHEN** a client declares `signals=["embedding","text","graph"]` and the validation file restricts the bucket to `allowed_signals: [embedding, text]`
- **THEN** a warning is emitted identifying `graph` as outside the allow-list
- **AND** construction succeeds and the `graph` layer remains enabled

#### Scenario: Missing validation file means no check

- **WHEN** no `citenexus.validate.yaml` is provided
- **THEN** no validation warning is emitted and construction proceeds normally
