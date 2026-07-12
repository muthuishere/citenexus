"""Per-leaf LanceDB vector store (spec §6b).

Each leaf partition gets its OWN LanceDB database (its own ``s3://…/vector/<P>/``
URI), not a shared table with a partition column. Physical separation gives clean
isolation (drop a leaf = drop a prefix) and small, fast indexes. The same class
works over a local path (hermetic tests) and ``s3://…`` (MinIO/prod) via
``storage_options``.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

import lancedb

from citenexus.storage.bm25 import Bm25TextSearch

if TYPE_CHECKING:
    from collections.abc import Sequence

# storage_options keys for S3/MinIO: endpoint, allow_http, access_key_id,
# secret_access_key, region.
StorageOptions = dict[str, str]


class LanceVectorStore:
    """The vector index for a single leaf partition."""

    TABLE = "evidence_units"

    def __init__(self, uri: str, storage_options: StorageOptions | None = None) -> None:
        self._db = lancedb.connect(uri, storage_options=storage_options or {})

    def _tables(self) -> list[str]:
        # table_names() returns a plain list of names; list_tables() returns a
        # version-dependent paginated object. The former is clearer here.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            names: list[str] = list(self._db.table_names())
        return names

    def upsert(self, rows: Sequence[dict[str, Any]]) -> None:
        """Insert or update EU rows keyed by ``eu_id`` (idempotent)."""
        if not rows:
            return
        data = list(rows)
        if self.TABLE in self._tables():
            tbl = self._db.open_table(self.TABLE)
            (
                tbl.merge_insert("eu_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(data)
            )
        else:
            self._db.create_table(self.TABLE, data=data)

    def search(self, vector: Sequence[float], limit: int = 10) -> list[dict[str, Any]]:
        """Nearest rows to ``vector``; empty if the leaf has no table yet."""
        if self.TABLE not in self._tables():
            return []
        tbl = self._db.open_table(self.TABLE)
        hits: list[dict[str, Any]] = tbl.search(list(vector)).limit(limit).to_list()
        return hits

    def scan(self, limit: int | None = None) -> list[dict[str, Any]]:
        """All rows in this leaf (no query) — the corpus for lexical/structure
        retrievers. Empty if the leaf has no table yet."""
        if self.TABLE not in self._tables():
            return []
        tbl = self._db.open_table(self.TABLE)
        rows: list[dict[str, Any]] = tbl.to_arrow().to_pylist()
        return rows if limit is None else rows[:limit]

    def delete_document(self, document_id: str) -> None:
        """Remove every row for ``document_id`` — the inverse of ingest's upsert.

        No-op if the leaf has no table yet or nothing matches. Single quotes in
        the id are doubled so the predicate can't be broken (Lance filters are
        SQL-like); ``delete_document`` is the only narrow mutation the seam
        exposes — no raw predicate crosses the boundary."""
        if self.TABLE not in self._tables():
            return
        tbl = self._db.open_table(self.TABLE)
        escaped = document_id.replace("'", "''")
        tbl.delete(f"document_id = '{escaped}'")

    def drop(self) -> None:
        """Drop this leaf's table (the leaf becomes empty)."""
        if self.TABLE in self._tables():
            self._db.drop_table(self.TABLE)


class LanceTextSearch(Bm25TextSearch):
    """The text-search half of the Lance backend pairing.

    LanceDB has no server-side text ranking, so its ``TextSearch`` is the
    in-core BM25-lite over ``scan()`` — named here so each backend reads as a
    (vector, text) pair: ``LanceVectorStore`` + ``LanceTextSearch``, mirroring
    ``PostgresVectorStore`` (+ its native tsvector ``search_text``).
    """

    plugin_version = "lance-text-search-v1"

    def __init__(self, store: LanceVectorStore) -> None:
        super().__init__(store)


# Backward-compat alias for the pre-rename name.
LeafVectorStore = LanceVectorStore
