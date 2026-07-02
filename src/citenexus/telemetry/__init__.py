"""Telemetry & cost — one event stream, read two ways (spec §6c).

Observability and cost are not separate subsystems: every stage emits a
`StageEvent`, sinks fan it out, the cost view derives money from configured rates,
and the counters derive trust signals — all from the same partition-attributed
stream.
"""

from citenexus.telemetry.cost import (
    CostRates,
    CostRollup,
    EndpointRate,
    compute_cost,
    rollup_by_document,
    rollup_by_partition,
    rollup_by_stage,
    scoped,
)
from citenexus.telemetry.counters import (
    QualityCounters,
    count_citation_failures,
    count_refusals,
    groundedness_rate,
    quality_counters,
)
from citenexus.telemetry.events import (
    Cost,
    Outcome,
    PluginRef,
    Stage,
    StageEvent,
    TokenUsage,
    UnitCount,
)
from citenexus.telemetry.sinks import InMemorySink, StdoutSink, TelemetrySink

__all__ = [
    "Cost",
    "CostRates",
    "CostRollup",
    "EndpointRate",
    "InMemorySink",
    "Outcome",
    "PluginRef",
    "QualityCounters",
    "Stage",
    "StageEvent",
    "StdoutSink",
    "TelemetrySink",
    "TokenUsage",
    "UnitCount",
    "compute_cost",
    "count_citation_failures",
    "count_refusals",
    "groundedness_rate",
    "quality_counters",
    "rollup_by_document",
    "rollup_by_partition",
    "rollup_by_stage",
    "scoped",
]
