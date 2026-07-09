"""The Evidence Unit (EU) — the atomic retrievable object (spec §7).

Everything in CiteNexus is evidence-first: EUs are what retrieval returns, what
the graph is built from, and what every answer cites. The bbox-level ``Citation``
makes legal/medical provenance verifiable at the passage level.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from citenexus.domain.partition import PartitionPath

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


class DocumentMetadata(BaseModel):
    """Best-effort document-level metadata (§8/row 8) — title/author/created
    date/page count, read from each format's own real metadata API (PDF
    ``Document Info``, DOCX/PPTX ``core_properties``, HTML ``<title>``/
    ``<meta name="author">``). Every field is optional: a format either has
    no such concept (a CSV has no "author") or the source document simply
    didn't set it — absence is not extraction failure.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str | None = None
    author: str | None = None
    created: str | None = None  # ISO-ish string, as the source format gives it
    page_count: int | None = None


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
    # The owning document's title/author/created/page_count, denormalized onto
    # every EU from that document (same pattern as document_id) — row 8.
    document_metadata: DocumentMetadata | None = None

    # Deferred-RBAC metadata: opaque, caller-supplied, persisted but NEVER parsed
    # or schema-imposed by the library (§7c).
    acl: Any = None

    # Vectors (optional — populated by the embedding stage).
    dense_vector: tuple[float, ...] | None = None
    sparse_vector: dict[str, float] | None = None

    # Integrity.
    checksum: str | None = None
    source_checksum: str | None = None
