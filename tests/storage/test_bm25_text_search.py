"""Bm25TextSearch — the in-core TextSearch implementation (spec §10).

Text search is its own store seam, symmetric with VectorStore: Postgres brings
native tsvector, and THIS is what LanceDB (or any scan-capable store) uses — a
``TextSearch`` implementation that scores scanned rows with BM25-lite. Same
protocol, same ``_text_score`` row shape, so the lexical retriever has exactly
one path regardless of backend.
"""

from __future__ import annotations

from typing import Any

from citenexus.storage.bm25 import Bm25TextSearch
from citenexus.storage.protocols import TextSearch


class ScanStore:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def upsert(self, rows: Any) -> None: ...

    def search(self, vector: Any, limit: int = 10) -> list[dict[str, Any]]:
        return []

    def scan(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self._rows


def _rows() -> list[dict[str, Any]]:
    return [
        {"eu_id": "nda::0", "text": "The employee shall not disclose confidential information."},
        {"eu_id": "cats::0", "text": "Cats are small domestic animals."},
        {"eu_id": "contract::0", "text": "Termination requires thirty days notice."},
    ]


def test_satisfies_text_search_protocol() -> None:
    assert isinstance(Bm25TextSearch(ScanStore([])), TextSearch)


def test_ranks_matching_rows_with_text_score() -> None:
    hits = Bm25TextSearch(ScanStore(_rows())).search_text("disclose confidential", limit=2)
    assert hits[0]["eu_id"] == "nda::0"
    assert hits[0]["_text_score"] > 0.0
    # non-matching rows are not returned
    assert all("cats" not in h["eu_id"] for h in hits)


def test_empty_corpus_or_query_returns_nothing() -> None:
    assert Bm25TextSearch(ScanStore([])).search_text("anything") == []
    assert Bm25TextSearch(ScanStore(_rows())).search_text("") == []


def test_limit_is_respected() -> None:
    rows = [{"eu_id": f"d{i}::0", "text": f"notice clause {i}"} for i in range(10)]
    hits = Bm25TextSearch(ScanStore(rows)).search_text("notice", limit=3)
    assert len(hits) == 3
