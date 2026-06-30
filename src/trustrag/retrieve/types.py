"""Shared retrieval types — the seam between retrievers, fusion, and the engine.

Each retriever (vector, lexical, structure, graph, community, wiki) returns a
ranked list of ``Candidate``s. RRF fusion merges those lists by ``eu_id``; wiki /
community candidates resolve **down** to their underlying EUs before citation
(navigate-not-cite, §10b). Every candidate carries enough to build a Result
``SourceRef`` without another store round-trip.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class RetrievalSignal(StrEnum):
    """Which retriever produced a candidate."""

    vector = "vector"
    lexical = "lexical"
    structure = "structure"
    graph = "graph"
    community = "community"
    wiki = "wiki"


class Candidate(BaseModel):
    """One scored retrieval hit, resolved to a citable Evidence Unit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eu_id: str
    score: float
    signal: RetrievalSignal
    document_id: str | None = None
    text: str | None = None
    page: int | None = None
    language: str | None = None
    checksum: str | None = None
    raw_uri: str | None = None
