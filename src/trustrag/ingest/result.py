"""The result of an ingest call."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class IngestResult(BaseModel):
    """What an ``IngestPipeline.ingest`` call produced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    status: str  # "ingested" | "unchanged"
    eu_ids: tuple[str, ...] = ()
    n_units: int = 0
    enqueued_slow_path: bool = False
