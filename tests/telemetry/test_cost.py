"""Cost view — the SAME events rolled up by stage / document / partition (§6c)."""

from pytest import approx

from trustrag.domain import PartitionPath
from trustrag.telemetry import (
    CostRates,
    EndpointRate,
    Stage,
    StageEvent,
    TokenUsage,
    UnitCount,
    compute_cost,
    rollup_by_document,
    rollup_by_partition,
    rollup_by_stage,
    scoped,
)

ACME = PartitionPath.of(("org", "acme"), ("product_line", "contracts"))
GLOBEX = PartitionPath.of(("org", "globex"), ("product_line", "hr"))

RATES = CostRates(
    rates={
        Stage.embedding: EndpointRate(input_per_1k=0.10),
        Stage.vision: EndpointRate(per_image=0.01),
        Stage.rerank: EndpointRate(per_candidate=0.002),
        Stage.generate: EndpointRate(input_per_1k=0.50, output_per_1k=1.50),
    }
)


def test_compute_cost_from_tokens() -> None:
    e = StageEvent(
        stage=Stage.generate,
        partition=ACME,
        tokens=TokenUsage(input=1000, output=2000),
    )
    # 1000/1k * 0.50 + 2000/1k * 1.50 = 0.50 + 3.00
    assert compute_cost(e, RATES) == approx(3.5)


def test_compute_cost_from_units() -> None:
    vision = StageEvent(stage=Stage.vision, partition=ACME, units=UnitCount(images=4))
    rerank = StageEvent(stage=Stage.rerank, partition=ACME, units=UnitCount(candidates=50))
    assert compute_cost(vision, RATES) == approx(0.04)
    assert compute_cost(rerank, RATES) == approx(0.1)


def test_unconfigured_stage_costs_zero() -> None:
    e = StageEvent(stage=Stage.chunk, partition=ACME, tokens=TokenUsage(input=10_000))
    assert compute_cost(e, RATES) == 0.0


def test_rollup_by_stage_totals() -> None:
    events = [
        StageEvent(stage=Stage.embedding, partition=ACME, tokens=TokenUsage(input=2000)),
        StageEvent(stage=Stage.embedding, partition=ACME, tokens=TokenUsage(input=1000)),
        StageEvent(stage=Stage.vision, partition=ACME, units=UnitCount(images=3)),
    ]
    rollup = rollup_by_stage(events, RATES)
    assert rollup.by_stage[Stage.embedding] == approx(0.3)  # 3000/1k * 0.10
    assert rollup.by_stage[Stage.vision] == approx(0.03)
    assert rollup.total == approx(0.33)


def test_rollup_by_document() -> None:
    events = [
        StageEvent(
            stage=Stage.embedding,
            partition=ACME,
            document_id="doc-a",
            tokens=TokenUsage(input=1000),
        ),
        StageEvent(
            stage=Stage.vision,
            partition=ACME,
            document_id="doc-b",
            units=UnitCount(images=2),
        ),
    ]
    by_doc = rollup_by_document(events, RATES)
    assert by_doc["doc-a"].total == approx(0.1)
    assert by_doc["doc-b"].total == approx(0.02)


def test_rollup_by_partition_attributes_per_org() -> None:
    events = [
        StageEvent(stage=Stage.generate, partition=ACME, tokens=TokenUsage(input=1000)),
        StageEvent(stage=Stage.generate, partition=GLOBEX, tokens=TokenUsage(input=2000)),
    ]
    by_part = rollup_by_partition(events, RATES)
    assert by_part[ACME].total == approx(0.5)
    assert by_part[GLOBEX].total == approx(1.0)


def test_scoped_filters_by_partition_prefix() -> None:
    org_scope = PartitionPath.of(("org", "acme"))
    events = [
        StageEvent(stage=Stage.generate, partition=ACME, tokens=TokenUsage(input=1000)),
        StageEvent(stage=Stage.generate, partition=GLOBEX, tokens=TokenUsage(input=2000)),
    ]
    acme_only = scoped(events, org_scope)
    assert len(acme_only) == 1
    assert rollup_by_stage(acme_only, RATES).total == approx(0.5)
