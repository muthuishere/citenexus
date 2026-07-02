"""StageEvent — the single telemetry event read two ways (spec §6c).

Observability and cost are *one* event stream, not two. Every pipeline stage
emits a `StageEvent` carrying timing, token/unit counts, an optional pre-attached
cost, the producing plugin, and an outcome. Because every event also carries its
`PartitionPath`, per-org / per-product-line cost attribution and quality counters
fall out of the same stream for free (the cost and counters modules read it).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from citenexus.domain import PartitionPath


class Stage(StrEnum):
    """The pipeline stage that emitted the event — ingest, retrieval, or answer."""

    extract = "extract"
    ocr = "ocr"
    vision = "vision"
    chunk = "chunk"
    embedding = "embedding"
    graph = "graph"
    community = "community"
    retrieve_vector = "retrieve_vector"
    retrieve_lexical = "retrieve_lexical"
    retrieve_graph = "retrieve_graph"
    retrieve_community = "retrieve_community"
    retrieve_structure = "retrieve_structure"
    fusion = "fusion"
    rerank = "rerank"
    verify = "verify"
    generate = "generate"
    judge = "judge"


class Outcome(StrEnum):
    """How the stage resolved — drives the quality counters (§6c)."""

    ok = "ok"
    retry = "retry"
    dead_letter = "dead_letter"
    refused = "refused"
    verify_failed = "verify_failed"


class TokenUsage(BaseModel):
    """LLM/embedding token counts for one stage call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input: int = 0
    output: int = 0


class UnitCount(BaseModel):
    """Non-token billable units — images, pages, rerank candidates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    images: int = 0
    pages: int = 0
    candidates: int = 0


class Cost(BaseModel):
    """A pre-attached money amount with its currency and basis of computation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: float
    currency: str
    basis: str


class PluginRef(BaseModel):
    """The producing plugin and its version, for attribution and rebuild diffing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    plugin_version: str


class StageEvent(BaseModel):
    """One thing that happened in the pipeline, attributed to a partition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Stage
    partition: PartitionPath
    document_id: str | None = None
    duration_ms: float = 0.0
    tokens: TokenUsage | None = None
    units: UnitCount | None = None
    cost: Cost | None = None
    plugin: PluginRef | None = None
    outcome: Outcome = Outcome.ok
