"""The sparse / lexical retrieval signal (spec §10).

``LexicalRetriever`` consumes the ``TextSearch`` store seam — ONE code path,
whatever the backend: Postgres ranks natively with ``tsvector``; LanceDB (or any
scan-capable store) is wrapped in the in-core ``Bm25TextSearch``. Passing a
plain ``VectorStore`` wraps it automatically, so backends that rank text
themselves are used as-is and everything else gets BM25-lite.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from trustrag.plugins.base import RetrieverPlugin
from trustrag.retrieve.types import Candidate, RetrievalSignal
from trustrag.storage.bm25 import Bm25TextSearch
from trustrag.storage.protocols import TextSearch

if TYPE_CHECKING:
    from trustrag.storage.protocols import VectorStore


def _page(value: object) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    return None


class LexicalRetriever(RetrieverPlugin):
    """Lexical retrieval over the injected ``TextSearch`` store seam."""

    plugin_version = "lexical-text-search-v1"

    def __init__(self, source: TextSearch | VectorStore) -> None:
        # A backend with native text ranking is used as-is; anything else is
        # wrapped in BM25-lite over its scan() — resolved once, at construction.
        self._text: TextSearch = (
            source if isinstance(source, TextSearch) else Bm25TextSearch(source)
        )

    def retrieve(self, query: str, k: int) -> list[Candidate]:
        candidates: list[Candidate] = []
        for row in self._text.search_text(query, limit=k):
            candidates.append(
                Candidate(
                    eu_id=str(row["eu_id"]),
                    score=float(row.get("_text_score", 0.0)),
                    signal=RetrievalSignal.lexical,
                    document_id=row.get("document_id"),
                    text=row.get("text"),
                    page=_page(row.get("page")),
                    language=row.get("language"),
                    checksum=row.get("checksum"),
                    raw_uri=row.get("raw_uri"),
                )
            )
        return candidates
