## ADDED Requirements

### Requirement: One partition-attributed stage event

The system SHALL define a single `StageEvent` for every pipeline stage, carrying
the `stage`, the emitting `PartitionPath`, an optional `document_id`,
`duration_ms`, optional token counts (input/output), optional unit counts
(images/pages/candidates), an optional pre-attached `cost` (amount/currency/basis),
the optional producing `plugin` (name/plugin_version), and an `outcome`. The model
SHALL be frozen and reject unknown fields, and SHALL round-trip losslessly through
JSON. The `stage` SHALL range over extract, ocr, vision, chunk, embedding, graph,
community, retrieve_vector, retrieve_lexical, retrieve_graph, retrieve_community,
retrieve_structure, fusion, rerank, verify, generate, and judge; the `outcome` over
ok, retry, dead_letter, refused, and verify_failed.

#### Scenario: Event round-trips losslessly

- **WHEN** a fully-populated `StageEvent` (tokens, units, cost, plugin, outcome) is
  serialized to JSON and parsed back
- **THEN** the resulting event equals the original, including its partition path

#### Scenario: Event rejects unknown fields

- **WHEN** a `StageEvent` is constructed with a key outside its defined fields
- **THEN** construction is rejected (the model forbids extra fields)

### Requirement: Pluggable telemetry sinks

The system SHALL expose a `TelemetrySink` structural protocol with a single
`emit(event)` method, so any operator-supplied sink is accepted without CiteNexus
depending on it. It SHALL ship an `InMemorySink` that collects emitted events in
order and a `StdoutSink` that writes each event as one JSON line to a stream.

#### Scenario: In-memory sink captures events in order

- **WHEN** several events are emitted to an `InMemorySink`
- **THEN** the sink's collected events equal the emitted events in emission order

#### Scenario: Stdout sink writes one JSON line per event

- **WHEN** two events are emitted to a `StdoutSink` bound to a text stream
- **THEN** the stream holds exactly two lines, each a JSON document that parses
  back into the emitted event

### Requirement: Cost derived from configured rates

The system SHALL compute an event's cost from its token and unit counts times a
configured per-endpoint rate card (`CostRates`, supplied by the operator), with
token rates charged per 1000 tokens. When no rate is configured for the event's
stage, the system SHALL fall back to any pre-attached cost amount, otherwise zero.

#### Scenario: Token cost uses the per-1k rate

- **WHEN** a generate event with 1000 input and 2000 output tokens is costed under
  rates of 0.50 per 1k input and 1.50 per 1k output
- **THEN** the computed cost is 3.50

#### Scenario: Unconfigured stage costs zero

- **WHEN** an event for a stage absent from the rate card and carrying no
  pre-attached cost is costed
- **THEN** the computed cost is 0.0

### Requirement: Cost rolls up by stage, document, and partition

The system SHALL roll up the same event stream into totals by stage, by
`document_id`, and by `PartitionPath`, each rollup exposing a per-stage breakdown
and a grand total. Because every event carries its partition path, per-org /
product-line attribution SHALL require no extra data.

#### Scenario: Rollup totals by stage

- **WHEN** a stream of embedding and vision events is rolled up by stage under a
  rate card
- **THEN** each stage's total equals the sum of its events' costs and the grand
  total equals the sum across stages

#### Scenario: Per-partition attribution

- **WHEN** events for two different organisation partitions are rolled up by
  partition
- **THEN** each partition's total reflects only its own events

### Requirement: Scope a stream by partition prefix

The system SHALL filter an event stream to the events whose partition lies within a
given scope's sub-tree, matched by partition prefix, so cost for any org or product
line is a prefix selection over the one stream.

#### Scenario: Prefix filter selects one org

- **WHEN** a stream mixing two organisations is scoped to one org's partition prefix
- **THEN** only that org's events remain, and their rollup reflects only those events

### Requirement: Quality counters over the event stream

The system SHALL derive trust counters from the same stream: the number of refused
outcomes, the number of verify-stage citation failures (verify_failed outcomes),
and the **groundedness rate** — the share of verify-stage claims whose outcome is
ok. The rate SHALL be 1.0 when the stream contains no verify-stage events. The
metric SHALL be named groundedness, never hallucination, because a hallucination
rate is uncomputable without ground truth.

#### Scenario: Count refusals and citation failures

- **WHEN** counters are computed over a stream containing refused outcomes and
  verify-stage verify_failed outcomes
- **THEN** the refusal count equals the number of refused outcomes and the citation
  failure count equals the number of verify-stage verify_failed outcomes

#### Scenario: Groundedness rate is the passing share

- **WHEN** the stream has four verify-stage events of which three passed
  faithfulness (outcome ok)
- **THEN** the groundedness rate is 0.75

#### Scenario: No claims yields full groundedness

- **WHEN** the stream contains no verify-stage events
- **THEN** the groundedness rate is 1.0
