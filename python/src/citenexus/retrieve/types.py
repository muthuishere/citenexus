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
    #: What the EU was INDEXED as. Under contextual retrieval (spec §7) this carries
    #: a small model's situating blurb ahead of the source text -- great for ranking,
    #: but it is NOT the customer's words. Never quote it; see ``citable_text``.
    text: str | None = None
    #: The VERBATIM chunk, as written by the source document. This is the only text
    #: that may be shown or attributed to the source.
    passage: str | None = None
    page: int | None = None
    language: str | None = None
    checksum: str | None = None
    raw_uri: str | None = None
    #: Caller-supplied source metadata as canonical JSON (ADR-0004), carried from
    #: the ``authority_meta`` row column. Opaque here: only an ``AuthorityProfile``
    #: interprets it, and it is METADATA — a tier is never derived from the text
    #: above. ``""`` on rows written before the column existed ⇒ unranked.
    authority_meta: str = ""

    @property
    def citable_text(self) -> str:
        """The text that may be quoted, generated from, and verified against.

        Falls back to ``text`` for rows indexed before ``passage`` was persisted:
        those indexes are un-migrated, not broken, and degrading to the old
        behaviour beats refusing to answer at all. Re-ingest to get the guarantee.
        """
        return self.passage if self.passage is not None else (self.text or "")
