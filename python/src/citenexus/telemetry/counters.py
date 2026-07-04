"""Quality counters — the same event stream read for trust signals (spec §6c).

These count what the pipeline actually did: how often it refused, how many claims
failed the citation/faithfulness gate, and the **groundedness rate** — the share
of verified claims that passed faithfulness. It is deliberately *not* a
"hallucination rate": without ground truth that number is uncomputable, so we name
and measure only what the evidence supports.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from citenexus.telemetry.events import Outcome, Stage, StageEvent


class QualityCounters(BaseModel):
    """Aggregate trust signals over one event stream."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    refusals: int
    citation_failures: int
    claims_total: int
    claims_grounded: int
    groundedness_rate: float


def count_refusals(events: Iterable[StageEvent]) -> int:
    """Number of events that ended in a refusal."""
    return sum(1 for e in events if e.outcome is Outcome.refused)


def count_citation_failures(events: Iterable[StageEvent]) -> int:
    """Number of verify-stage claims that failed the citation/faithfulness gate."""
    return sum(1 for e in events if e.stage is Stage.verify and e.outcome is Outcome.verify_failed)


def groundedness_rate(events: Iterable[StageEvent]) -> float:
    """Share of verify-stage claims that passed faithfulness — 1.0 when there are none."""
    total = 0
    grounded = 0
    for e in events:
        if e.stage is not Stage.verify:
            continue
        total += 1
        if e.outcome is Outcome.ok:
            grounded += 1
    if total == 0:
        return 1.0
    return grounded / total


def quality_counters(events: Iterable[StageEvent]) -> QualityCounters:
    """All trust signals in one pass over the stream."""
    materialized = tuple(events)
    refusals = count_refusals(materialized)
    citation_failures = count_citation_failures(materialized)
    verifies = [e for e in materialized if e.stage is Stage.verify]
    claims_total = len(verifies)
    claims_grounded = sum(1 for e in verifies if e.outcome is Outcome.ok)
    rate = 1.0 if claims_total == 0 else claims_grounded / claims_total
    return QualityCounters(
        refusals=refusals,
        citation_failures=citation_failures,
        claims_total=claims_total,
        claims_grounded=claims_grounded,
        groundedness_rate=rate,
    )
