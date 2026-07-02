## Why

Production RAG in regulated domains has to answer two operator questions from day
one — "what did this cost?" and "can I trust the answers?" — and the cheap way to
answer both is to recognise they are the *same* event stream read two ways (§6c).
Bolting on a separate metrics system and a separate billing system duplicates the
emit path and lets the two drift. CiteNexus instead emits one partition-attributed
`StageEvent` per pipeline stage; cost and quality are pure views over that stream.

## What Changes

- Add a **`StageEvent`** model: the stage (`extract`…`judge`), the `PartitionPath`,
  optional `document_id`, `duration_ms`, token counts, unit counts (images/pages/
  candidates), an optional pre-attached `cost`, the producing `plugin`, and an
  `outcome` (`ok`/`retry`/`dead_letter`/`refused`/`verify_failed`).
- Add a **pluggable sink seam**: a `TelemetrySink` structural protocol plus two
  built-ins — `StdoutSink` (one JSON line per event) and `InMemorySink` (collects
  events, for tests and the cost view).
- Add the **cost view**: a `CostRates` rate card (per-endpoint token/unit prices,
  passed in by the operator) and rollup functions that total cost by stage, by
  document, and by partition from the same events — plus `scoped()` for per-org /
  product-line attribution by partition prefix.
- Add **quality counters**: refusals, citation failures, and the **groundedness
  rate** (share of verify-stage claims that passed faithfulness). Deliberately
  *not* a "hallucination rate" — uncomputable without ground truth.

No I/O, no network, no new dependencies; pure models and pure functions over an
in-memory stream. Sinks are where I/O would later live, behind the protocol.

## Capabilities

### New Capabilities
- `telemetry-cost`: one partition-attributed `StageEvent` stream, a pluggable sink
  seam, a cost view (rates → rollups by stage/document/partition), and quality
  counters (refusals, citation failures, groundedness rate).

### Modified Capabilities
<!-- none -->

## Impact

- New module `src/citenexus/telemetry/`: `events.py`, `sinks.py`, `cost.py`,
  `counters.py`, `__init__.py`.
- Reuses `citenexus.domain.PartitionPath` — every event carries the path, so
  per-org / product-line attribution is a group-by and prefix filter (§6b, §7c).
- Downstream: ingest (L3), retrieval (L4), and answer/verify (L5) emit events to
  the configured sink; the worker (L2) reports retry/dead-letter outcomes; the
  evaluate front door (§20) reads counters for groundedness/citation/refusal
  metrics.
