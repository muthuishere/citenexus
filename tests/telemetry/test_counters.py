"""Quality counters — refusals, citation failures, groundedness rate (§6c).

Named *groundedness*, never *hallucination*: without ground truth the share of
claims that passed the faithfulness gate is all we can honestly compute.
"""

from trustrag.domain import PartitionPath
from trustrag.telemetry import (
    Outcome,
    Stage,
    StageEvent,
    count_citation_failures,
    count_refusals,
    groundedness_rate,
    quality_counters,
)

P = PartitionPath.of(("org", "acme"))


def _verify(outcome: Outcome) -> StageEvent:
    return StageEvent(stage=Stage.verify, partition=P, outcome=outcome)


def test_count_refusals() -> None:
    events = [
        StageEvent(stage=Stage.generate, partition=P, outcome=Outcome.refused),
        StageEvent(stage=Stage.generate, partition=P, outcome=Outcome.ok),
        StageEvent(stage=Stage.generate, partition=P, outcome=Outcome.refused),
    ]
    assert count_refusals(events) == 2


def test_count_citation_failures() -> None:
    events = [
        _verify(Outcome.ok),
        _verify(Outcome.verify_failed),
        _verify(Outcome.verify_failed),
        StageEvent(stage=Stage.generate, partition=P, outcome=Outcome.verify_failed),
    ]
    # only verify-stage failures are citation failures
    assert count_citation_failures(events) == 2


def test_groundedness_rate() -> None:
    events = [
        _verify(Outcome.ok),
        _verify(Outcome.ok),
        _verify(Outcome.ok),
        _verify(Outcome.verify_failed),
    ]
    assert groundedness_rate(events) == 0.75


def test_groundedness_rate_no_claims_is_one() -> None:
    assert groundedness_rate([]) == 1.0


def test_quality_counters_aggregate() -> None:
    events = [
        StageEvent(stage=Stage.generate, partition=P, outcome=Outcome.refused),
        _verify(Outcome.ok),
        _verify(Outcome.verify_failed),
    ]
    qc = quality_counters(events)
    assert qc.refusals == 1
    assert qc.citation_failures == 1
    assert qc.claims_total == 2
    assert qc.claims_grounded == 1
    assert qc.groundedness_rate == 0.5
