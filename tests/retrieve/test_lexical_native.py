"""Lexical signal delegates to a backend's NATIVE text search when available.

A ``VectorStore`` that also implements ``TextSearch`` (Postgres tsvector) ranks
text itself — indexed and scalable — so BM25-lite over ``scan()`` is only the
fallback for backends that can't (LanceDB).
"""

from __future__ import annotations

from typing import Any

from trustrag.retrieve.lexical import LexicalRetriever
from trustrag.retrieve.types import RetrievalSignal


class NativeTextStore:
    """A store with native text ranking; scan() would be the wrong path."""

    def __init__(self) -> None:
        self.text_queries: list[str] = []
        self.scan_calls = 0

    def upsert(self, rows: Any) -> None: ...

    def search(self, vector: Any, limit: int = 10) -> list[dict[str, Any]]:
        return []

    def scan(self, limit: int | None = None) -> list[dict[str, Any]]:
        self.scan_calls += 1
        return []

    def search_text(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        self.text_queries.append(query)
        return [
            {
                "eu_id": "doc::0",
                "text": "The employee shall not disclose.",
                "document_id": "doc",
                "language": "en",
                "page": 1,
                "checksum": "abc",
                "raw_uri": "raw/abc",
                "_text_score": 0.7,
            }
        ]


def test_native_text_search_is_used_when_available() -> None:
    store = NativeTextStore()
    out = LexicalRetriever(store).retrieve("disclose", k=3)
    assert store.text_queries == ["disclose"]
    assert store.scan_calls == 0  # never falls back to scanning
    assert out[0].eu_id == "doc::0"
    assert out[0].signal is RetrievalSignal.lexical
    assert out[0].score == 0.7
    assert out[0].page == 1


def test_bm25_fallback_still_works_without_native_search() -> None:
    class ScanOnlyStore:
        def upsert(self, rows: Any) -> None: ...

        def search(self, vector: Any, limit: int = 10) -> list[dict[str, Any]]:
            return []

        def scan(self, limit: int | None = None) -> list[dict[str, Any]]:
            return [
                {
                    "eu_id": "doc::0",
                    "text": "The employee shall not disclose confidential information.",
                    "document_id": "doc",
                }
            ]

    out = LexicalRetriever(ScanOnlyStore()).retrieve("disclose", k=3)
    assert out and out[0].eu_id == "doc::0"
