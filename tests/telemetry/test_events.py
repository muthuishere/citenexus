"""StageEvent — one typed event with partition attribution (spec §6c)."""

import pytest
from pydantic import ValidationError

from trustrag.domain import PartitionPath
from trustrag.telemetry import (
    Cost,
    Outcome,
    PluginRef,
    Stage,
    StageEvent,
    TokenUsage,
    UnitCount,
)


def _partition() -> PartitionPath:
    return PartitionPath.of(("org", "acme"), ("product_line", "contracts"))


def test_minimal_event_defaults() -> None:
    e = StageEvent(stage=Stage.generate, partition=_partition())
    assert e.outcome is Outcome.ok
    assert e.document_id is None
    assert e.tokens is None
    assert e.units is None
    assert e.cost is None
    assert e.plugin is None
    assert e.duration_ms == 0.0


def test_full_event_round_trip() -> None:
    e = StageEvent(
        stage=Stage.embedding,
        partition=_partition(),
        document_id="doc-1",
        duration_ms=12.5,
        tokens=TokenUsage(input=120, output=0),
        units=UnitCount(images=0, pages=2, candidates=0),
        cost=Cost(amount=0.0012, currency="USD", basis="tokens"),
        plugin=PluginRef(name="bge-m3", plugin_version="1.0.0"),
        outcome=Outcome.ok,
    )
    again = StageEvent.model_validate_json(e.model_dump_json())
    assert again == e
    assert again.partition == _partition()


def test_event_is_frozen() -> None:
    e = StageEvent(stage=Stage.rerank, partition=_partition())
    with pytest.raises(ValidationError):
        e.stage = Stage.verify  # type: ignore[misc]


def test_event_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        StageEvent(stage=Stage.verify, partition=_partition(), bogus=1)  # type: ignore[call-arg]


def test_stage_and_outcome_members() -> None:
    assert Stage.retrieve_community == "retrieve_community"
    assert Stage.retrieve_structure == "retrieve_structure"
    assert Outcome.dead_letter == "dead_letter"
    assert Outcome.verify_failed == "verify_failed"
