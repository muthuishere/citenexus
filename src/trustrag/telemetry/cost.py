"""Cost view — the same event stream rolled up by money (spec §6c).

Cost is *derived*, not stored: configured per-endpoint `CostRates` (passed in by
the operator) turn each event's `tokens` / `units` into an amount, which then
rolls up by stage, by document, or by partition. Since every `StageEvent` carries
its `PartitionPath`, per-org / per-product-line attribution is just a group-by —
and `scoped()` narrows the stream to any partition sub-tree by prefix.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from trustrag.domain import PartitionPath
from trustrag.telemetry.events import Stage, StageEvent


class EndpointRate(BaseModel):
    """Per-endpoint unit prices for one stage. Token rates are per 1k tokens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_per_1k: float = 0.0
    output_per_1k: float = 0.0
    per_image: float = 0.0
    per_page: float = 0.0
    per_candidate: float = 0.0


class CostRates(BaseModel):
    """The operator-supplied rate card: a price per stage endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rates: dict[Stage, EndpointRate]
    currency: str = "USD"


class CostRollup(BaseModel):
    """Cost totalled by stage, plus the grand total, in one currency."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    by_stage: dict[Stage, float]
    total: float
    currency: str = "USD"


def compute_cost(event: StageEvent, rates: CostRates) -> float:
    """Money for one event: its `tokens`/`units` times the stage's configured rate.

    When no rate is configured for the stage, fall back to any pre-attached
    `event.cost.amount`, else zero.
    """
    rate = rates.rates.get(event.stage)
    if rate is None:
        return event.cost.amount if event.cost is not None else 0.0
    amount = 0.0
    if event.tokens is not None:
        amount += event.tokens.input / 1000 * rate.input_per_1k
        amount += event.tokens.output / 1000 * rate.output_per_1k
    if event.units is not None:
        amount += event.units.images * rate.per_image
        amount += event.units.pages * rate.per_page
        amount += event.units.candidates * rate.per_candidate
    return amount


def rollup_by_stage(events: Iterable[StageEvent], rates: CostRates) -> CostRollup:
    """Total cost per stage over a stream — also the per-query view (pass a query's events)."""
    by_stage: dict[Stage, float] = {}
    total = 0.0
    for event in events:
        amount = compute_cost(event, rates)
        by_stage[event.stage] = by_stage.get(event.stage, 0.0) + amount
        total += amount
    return CostRollup(by_stage=by_stage, total=total, currency=rates.currency)


def rollup_by_document(events: Iterable[StageEvent], rates: CostRates) -> dict[str, CostRollup]:
    """Per-document cost rollups, keyed by `document_id` (events without one are skipped)."""
    grouped: dict[str, list[StageEvent]] = {}
    for event in events:
        if event.document_id is None:
            continue
        grouped.setdefault(event.document_id, []).append(event)
    return {doc: rollup_by_stage(evs, rates) for doc, evs in grouped.items()}


def rollup_by_partition(
    events: Iterable[StageEvent], rates: CostRates
) -> dict[PartitionPath, CostRollup]:
    """Per-partition cost rollups — free org / product-line attribution."""
    grouped: dict[PartitionPath, list[StageEvent]] = {}
    for event in events:
        grouped.setdefault(event.partition, []).append(event)
    return {part: rollup_by_stage(evs, rates) for part, evs in grouped.items()}


def scoped(events: Iterable[StageEvent], scope: PartitionPath) -> tuple[StageEvent, ...]:
    """Just the events whose partition lies in `scope`'s sub-tree (prefix match)."""
    return tuple(event for event in events if scope.is_prefix_of(event.partition))
