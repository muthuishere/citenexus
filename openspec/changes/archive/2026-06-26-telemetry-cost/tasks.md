## 1. Tests first (red)

- [x] 1.1 `tests/telemetry/test_events.py`: minimal-defaults event; full event
      JSON round-trip equal (incl. partition); frozen + extra-forbid rejection;
      Stage/Outcome member values.
- [x] 1.2 `tests/telemetry/test_sinks.py`: `InMemorySink` captures in order and
      satisfies `TelemetrySink`; `StdoutSink` writes one parseable JSON line per
      event; a function typed on the protocol accepts any sink.
- [x] 1.3 `tests/telemetry/test_cost.py`: token cost via per-1k rate; unit cost via
      per-image/per-candidate rate; unconfigured stage ⇒ 0.0; rollup by stage
      (totals + grand total); rollup by document; rollup by partition (per-org
      attribution); `scoped()` prefix filter.
- [x] 1.4 `tests/telemetry/test_counters.py`: refusal count; verify-stage citation
      failures only; groundedness rate (0.75 case); empty stream ⇒ 1.0; aggregate
      `quality_counters` model.

## 2. Implement (green)

- [x] 2.1 `src/citenexus/telemetry/events.py`: `Stage` + `Outcome` StrEnums;
      `TokenUsage`, `UnitCount`, `Cost`, `PluginRef` sub-models; frozen,
      extra-forbid `StageEvent` carrying a `PartitionPath`.
- [x] 2.2 `src/citenexus/telemetry/sinks.py`: `TelemetrySink` runtime-checkable
      protocol; `StdoutSink` (JSON line per event); `InMemorySink` (collector).
- [x] 2.3 `src/citenexus/telemetry/cost.py`: `EndpointRate` + `CostRates` rate card;
      `CostRollup`; `compute_cost`; `rollup_by_stage` / `rollup_by_document` /
      `rollup_by_partition`; `scoped` prefix filter.
- [x] 2.4 `src/citenexus/telemetry/counters.py`: `count_refusals`,
      `count_citation_failures`, `groundedness_rate`, and the `QualityCounters`
      aggregate model + `quality_counters`.
- [x] 2.5 `src/citenexus/telemetry/__init__.py`: export the models, sinks, cost
      functions, and counters.

## 3. Verify

- [x] 3.1 `uv run pytest tests/telemetry -q` green.
- [x] 3.2 `uv run ruff check src/citenexus/telemetry tests/telemetry` clean.
- [x] 3.3 `uv run mypy src/citenexus/telemetry tests/telemetry` clean (strict).
- [x] 3.4 `npx -y @fission-ai/openspec@latest validate telemetry-cost` reports valid.
