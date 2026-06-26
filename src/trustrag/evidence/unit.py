"""The Evidence Unit (EU) — the atomic retrievable object (spec §7).

Everything in TrustRAG is evidence-first: EUs are what retrieval returns, what
the graph is built from, and what every answer cites. The bbox-level ``Citation``
makes legal/medical provenance verifiable at the passage level.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from trustrag.domain.partition import PartitionPath

# A bounding box as [x0, y0, x1, y1] in page coordinates — exactly four numbers.
BBox = tuple[float, float, float, float]


class EUType(StrEnum):
    """The closed set of Evidence Unit types (§7)."""

    paragraph = "paragraph"
    section = "section"
    table = "table"
    figure = "figure"
    image = "image"
    chart = "chart"
    diagram = "diagram"
    code_block = "code_block"
    ocr_block = "ocr_block"
    page_summary = "page_summary"
    document_summary = "document_summary"
    community_summary = "community_summary"


class Citation(BaseModel):
    """Verifiable provenance for a passage: page + bbox + the verbatim text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passage: str
    page: int | None = None
    bbox: BBox | None = None


class EvidenceUnit(BaseModel):
    """The smallest retrievable evidence object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Identity + content (required).
    eu_id: str
    partition: PartitionPath
    document_id: str
    type: EUType
    language: str
    text: str
    citation: Citation

    # Layout / metadata (optional).
    page: int | None = None
    section: str | None = None
    source_uri: str | None = None
    entities: tuple[str, ...] = ()
    structure_path: tuple[str, ...] | None = None

    # Deferred-RBAC metadata: opaque, caller-supplied, persisted but NEVER parsed
    # or schema-imposed by the library (§7c).
    acl: Any = None

    # Vectors (optional — populated by the embedding stage).
    dense_vector: tuple[float, ...] | None = None
    sparse_vector: dict[str, float] | None = None

    # Integrity.
    checksum: str | None = None
    source_checksum: str | None = None
