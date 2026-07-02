"""``PostgresVectorStore`` — pgvector + native tsvector text search (spec §6b).

The second ``VectorStore`` implementation, so a team with Postgres brings their
own database instead of adopting LanceDB. Semantics mirror the LanceDB
reference: **one table per leaf partition** (isolation = drop a table), the same
dict-shaped EU rows, and ``search`` results carrying ``_distance``.

It ALSO implements ``TextSearch``: Postgres ranks text natively with
``tsvector`` / ``websearch_to_tsquery`` using the ``'simple'`` configuration —
no English stemming, so non-English evidence is never penalized (the same
language-agnostic stance as the in-core BM25-lite it replaces).

Dependencies stay honest: ``psycopg`` is an OPTIONAL extra
(``pip install trustrag[postgres]``), imported lazily at first connection —
construction does no IO, so config-driven wiring stays hermetic in tests. The
connection is injectable for unit tests.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_COLUMNS = ("eu_id", "text", "document_id", "language", "page", "checksum", "raw_uri")
_IDENT = re.compile(r"[^a-z0-9_]+")


def table_name_for(prefix: str, partition_segment: str) -> str:
    """A safe per-leaf table name from the configured prefix + partition."""
    leaf = _IDENT.sub("_", partition_segment.lower()).strip("_")
    return f"{_IDENT.sub('_', prefix.lower()).strip('_')}_{leaf}"


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in vector) + "]"


def _is_missing_table(error: Exception) -> bool:
    """True for Postgres 42P01 (undefined table) — an empty leaf, not a bug."""
    return getattr(error, "sqlstate", None) == "42P01" or type(error).__name__ == "UndefinedTable"


class PostgresVectorStore:
    """Per-leaf EU index on Postgres: pgvector dense + tsvector lexical."""

    plugin_version = "postgres-vector-v1"

    def __init__(
        self,
        *,
        dsn: str,
        table: str,
        connect: Callable[[], Any] | None = None,
    ) -> None:
        # Lazy everywhere: no import, no connection until first use.
        self._dsn = dsn
        self._table = table
        self._connect = connect
        self._conn: Any = None
        self._ready = False

    def _connection(self) -> Any:
        if self._conn is None:
            if self._connect is not None:
                self._conn = self._connect()
            else:
                try:
                    import psycopg
                except ImportError as error:  # pragma: no cover - import guard
                    raise ImportError(
                        "PostgresVectorStore needs the optional extra: "
                        "pip install 'trustrag[postgres]'"
                    ) from error
                self._conn = psycopg.connect(self._dsn)
        return self._conn

    def _ensure_table(self, dimension: int) -> None:
        if self._ready:
            return
        conn = self._connection()
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                "eu_id TEXT PRIMARY KEY, "
                f"vector vector({dimension}), "
                "text TEXT, document_id TEXT, language TEXT, "
                "page INTEGER, checksum TEXT, raw_uri TEXT)"
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {self._table}_fts ON {self._table} "
                "USING GIN (to_tsvector('simple', coalesce(text, '')))"
            )
        conn.commit()
        self._ready = True

    def upsert(self, rows: Sequence[dict[str, Any]]) -> None:
        """Insert or update EU rows keyed by ``eu_id`` (idempotent)."""
        if not rows:
            return
        self._ensure_table(len(rows[0]["vector"]))
        conn = self._connection()
        assignments = ", ".join(f"{c} = EXCLUDED.{c}" for c in ("vector", *_COLUMNS[1:]))
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    f"INSERT INTO {self._table} "
                    f"(eu_id, vector, {', '.join(_COLUMNS[1:])}) "
                    f"VALUES (%s, %s::vector, {', '.join('%s' for _ in _COLUMNS[1:])}) "
                    f"ON CONFLICT (eu_id) DO UPDATE SET {assignments}",
                    (
                        row["eu_id"],
                        _vector_literal(row["vector"]),
                        *(row.get(c) for c in _COLUMNS[1:]),
                    ),
                )
        conn.commit()

    def _select(self, sql: str, params: tuple[Any, ...] | None) -> list[tuple[Any, ...]]:
        """Run a SELECT; an undefined table is an empty leaf (parity with LanceDB)."""
        conn = self._connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows: list[tuple[Any, ...]] = cur.fetchall()
            return rows
        except Exception as error:
            if _is_missing_table(error):
                rollback = getattr(conn, "rollback", None)
                if callable(rollback):
                    rollback()
                return []
            raise

    def search(self, vector: Sequence[float], limit: int = 10) -> list[dict[str, Any]]:
        """Nearest rows by pgvector cosine distance (``<=>``), with ``_distance``."""
        rows = self._select(
            f"SELECT {', '.join(_COLUMNS)}, vector <=> %s::vector AS _distance "
            f"FROM {self._table} ORDER BY _distance LIMIT %s",
            (_vector_literal(vector), limit),
        )
        return [dict(zip((*_COLUMNS, "_distance"), row, strict=True)) for row in rows]

    def search_text(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Native lexical ranking via tsvector ('simple' config — no stemming)."""
        rows = self._select(
            f"SELECT {', '.join(_COLUMNS)}, "
            "ts_rank(to_tsvector('simple', coalesce(text, '')), "
            "websearch_to_tsquery('simple', %s)) AS _text_score "
            f"FROM {self._table} "
            "WHERE to_tsvector('simple', coalesce(text, '')) @@ "
            "websearch_to_tsquery('simple', %s) "
            "ORDER BY _text_score DESC LIMIT %s",
            (query, query, limit),
        )
        return [dict(zip((*_COLUMNS, "_text_score"), row, strict=True)) for row in rows]

    def scan(self, limit: int | None = None) -> list[dict[str, Any]]:
        """All rows in this leaf — the corpus for lexical/structure signals."""
        sql = f"SELECT {', '.join(_COLUMNS)} FROM {self._table}"
        params: tuple[Any, ...] | None = None
        if limit is not None:
            sql += " LIMIT %s"
            params = (limit,)
        rows = self._select(sql, params)
        return [dict(zip(_COLUMNS, row, strict=True)) for row in rows]
