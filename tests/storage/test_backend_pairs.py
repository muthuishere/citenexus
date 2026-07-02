"""Each storage backend is a named (vector, text) pair behind the two protocols.

- Lance:    LanceVectorStore    + LanceTextSearch    (BM25-lite over scan)
- Postgres: PostgresVectorStore + PostgresTextSearch (native tsvector)

The names ARE the architecture: pick a backend, get both halves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from trustrag.storage import (
    LanceTextSearch,
    LanceVectorStore,
    LeafVectorStore,
    PostgresTextSearch,
    PostgresVectorStore,
    TextSearch,
    VectorStore,
)


def test_lance_pair_satisfies_the_protocols(tmp_path: Path) -> None:
    store = LanceVectorStore(str(tmp_path / "leaf"))
    assert isinstance(store, VectorStore)
    assert isinstance(LanceTextSearch(store), TextSearch)


def test_lance_text_search_ranks_scanned_rows(tmp_path: Path) -> None:
    store = LanceVectorStore(str(tmp_path / "leaf"))
    store.upsert(
        [
            {
                "eu_id": "nda::0",
                "vector": [1.0, 0.0],
                "text": "The employee shall not disclose confidential information.",
                "document_id": "nda",
                "language": "en",
                "page": -1,
                "checksum": "abc",
                "raw_uri": "raw/abc",
            }
        ]
    )
    hits = LanceTextSearch(store).search_text("disclose confidential")
    assert hits[0]["eu_id"] == "nda::0"
    assert hits[0]["_text_score"] > 0.0


def test_postgres_pair_satisfies_the_protocols() -> None:
    store = PostgresVectorStore(dsn="postgresql://ignored", table="t")  # lazy, no IO
    assert isinstance(store, VectorStore)
    assert isinstance(PostgresTextSearch(store), TextSearch)


def test_postgres_text_search_delegates_to_native() -> None:
    class Spy(PostgresVectorStore):
        def __init__(self) -> None:
            super().__init__(dsn="postgresql://ignored", table="t")
            self.queries: list[str] = []

        def search_text(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
            self.queries.append(query)
            return [{"eu_id": "x", "_text_score": 1.0}]

    spy = Spy()
    assert PostgresTextSearch(spy).search_text("notice") == [{"eu_id": "x", "_text_score": 1.0}]
    assert spy.queries == ["notice"]


def test_pre_rename_alias_still_works() -> None:
    assert LeafVectorStore is LanceVectorStore
