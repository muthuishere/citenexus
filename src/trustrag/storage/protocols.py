"""The vector-store and text-search seams (spec §6b, §10).

TrustRAG's storage is layered: raw blobs / manifests / graph / wiki artifacts
live behind ``StorageBackend`` (S3-native, already an adapter), while the
retrievable index lives behind these two protocols:

- ``VectorStore`` — the per-leaf index every consumer already uses through
  exactly three methods (``upsert`` / ``search`` / ``scan``). ``LeafVectorStore``
  (LanceDB) is the zero-infra, S3-native REFERENCE implementation and stays the
  default; ``PostgresVectorStore`` (pgvector) lets a team bring their existing
  Postgres instead.
- ``TextSearch`` — OPTIONAL native lexical search. A backend that can rank text
  itself (Postgres ``tsvector``) implements it and the lexical signal delegates;
  a backend that can't (LanceDB) simply doesn't, and the in-core BM25-lite over
  ``scan()`` is used. Runtime-checkable so the retriever can sniff support.

Rows are plain dicts with the EU keys the ingest pipeline writes: ``eu_id``,
``vector``, ``text``, ``document_id``, ``language``, ``page``, ``checksum``,
``raw_uri``. ``search`` results additionally carry ``_distance``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VectorStore(Protocol):
    """The per-leaf retrievable index — the seam all consumers go through."""

    def upsert(self, rows: Sequence[dict[str, Any]]) -> None:
        """Insert or update EU rows keyed by ``eu_id`` (idempotent)."""
        ...

    def search(self, vector: Sequence[float], limit: int = 10) -> list[dict[str, Any]]:
        """Nearest rows to ``vector`` (each with ``_distance``); [] when empty."""
        ...

    def scan(self, limit: int | None = None) -> list[dict[str, Any]]:
        """All rows in this leaf — the corpus for lexical/structure signals."""
        ...


@runtime_checkable
class TextSearch(Protocol):
    """Native lexical ranking, when the backend can do it itself."""

    def search_text(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Rows ranked by the backend's own text relevance (each with a score
        under ``_text_score``); [] when nothing matches."""
        ...
