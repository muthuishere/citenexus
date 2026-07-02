"""PostgresVectorStore — pgvector + native tsvector text search (spec §6b).

The second ``VectorStore`` implementation: teams with Postgres bring their own
database instead of adopting LanceDB. One table per leaf partition (same
isolation semantics as LanceDB-per-leaf); dense search via pgvector's cosine
operator, and NATIVE lexical ranking via ``tsvector`` — so this backend also
implements the ``TextSearch`` protocol and the lexical signal delegates to it.

Unit tests are hermetic: a fake connection records SQL and returns canned rows.
The real-server round-trip is the integration test (compose `postgres` profile).
"""

from __future__ import annotations

from typing import Any

from trustrag.storage.postgres_store import PostgresVectorStore
from trustrag.storage.protocols import TextSearch, VectorStore


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self._conn.statements.append((" ".join(sql.split()), params))
        self._rows = self._conn.rows_for(sql)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeConnection:
    """Records every statement; returns canned rows for SELECTs."""

    def __init__(self, select_rows: list[tuple[Any, ...]] | None = None) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.select_rows = select_rows or []
        self.commits = 0

    def rows_for(self, sql: str) -> list[tuple[Any, ...]]:
        return self.select_rows if sql.lstrip().upper().startswith("SELECT") else []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1


_ROW = {
    "eu_id": "doc::0",
    "vector": [0.1, 0.2, 0.3],
    "text": "The employee shall not disclose.",
    "document_id": "doc",
    "language": "en",
    "page": 1,
    "checksum": "abc",
    "raw_uri": "raw/abc",
}


def _store(conn: FakeConnection) -> PostgresVectorStore:
    return PostgresVectorStore(
        dsn="postgresql://ignored", table="trustrag_ws_default", connect=lambda: conn
    )


def test_satisfies_both_protocols() -> None:
    store = _store(FakeConnection())
    assert isinstance(store, VectorStore)
    assert isinstance(store, TextSearch)


def test_upsert_creates_table_with_vector_dimension() -> None:
    conn = FakeConnection()
    _store(conn).upsert([_ROW])
    blob = " ".join(sql for sql, _ in conn.statements)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in blob
    assert "vector(3)" in blob  # dimension inferred from the first row
    assert "ON CONFLICT (eu_id) DO UPDATE" in blob
    assert conn.commits >= 1


def test_upsert_empty_is_noop() -> None:
    conn = FakeConnection()
    _store(conn).upsert([])
    assert conn.statements == []


def test_search_orders_by_cosine_distance_and_maps_rows() -> None:
    conn = FakeConnection(
        select_rows=[
            ("doc::0", "The employee shall not disclose.", "doc", "en", 1, "abc", "raw/abc", 0.12)
        ]
    )
    hits = _store(conn).search([0.1, 0.2, 0.3], limit=5)
    sql = conn.statements[-1][0]
    assert "<=>" in sql  # pgvector cosine-distance operator
    assert "LIMIT" in sql
    assert hits[0]["eu_id"] == "doc::0"
    assert hits[0]["_distance"] == 0.12
    assert hits[0]["page"] == 1


def test_search_text_uses_native_tsvector_ranking() -> None:
    conn = FakeConnection(
        select_rows=[
            ("doc::0", "The employee shall not disclose.", "doc", "en", 1, "abc", "raw/abc", 0.61)
        ]
    )
    hits = _store(conn).search_text("disclose employee", limit=5)
    sql = conn.statements[-1][0]
    assert "websearch_to_tsquery" in sql
    assert "'simple'" in sql  # language-agnostic config — no English stemming
    assert hits[0]["_text_score"] == 0.61


def test_scan_returns_all_rows_as_dicts() -> None:
    conn = FakeConnection(select_rows=[("doc::0", "text a", "doc", "en", -1, "abc", "raw/abc")])
    rows = _store(conn).scan()
    assert rows[0]["eu_id"] == "doc::0"
    assert rows[0]["text"] == "text a"
    assert rows[0]["page"] == -1
