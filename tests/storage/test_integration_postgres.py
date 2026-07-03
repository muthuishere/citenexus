"""Opt-in Postgres/pgvector round-trip (task local:postgres:up).

The real-server proof for the second VectorStore backend: upsert → dense search
(pgvector cosine) → NATIVE text search (tsvector) → scan → idempotent re-upsert.
Skips unless psycopg is installed and Postgres answers on the compose port.
"""

from __future__ import annotations

import os
import socket
import uuid

import pytest

from citenexus.storage.postgres_store import PostgresVectorStore, table_name_for

DSN = os.environ.get(
    "CITENEXUS_PG_DSN", "postgresql://citenexus:citenexus@localhost:15432/citenexus"
)
_PORT = int(os.environ.get("CITENEXUS_PG_PORT", "15432"))


def _postgres_up() -> bool:
    try:
        socket.create_connection(("localhost", _PORT), timeout=2).close()
        return True
    except OSError:
        return False


@pytest.mark.integration
def test_postgres_round_trip() -> None:
    pytest.importorskip("psycopg")
    if not _postgres_up():
        pytest.skip(f"Postgres not reachable on localhost:{_PORT}")

    table = table_name_for("citenexus_it", f"workspace={uuid.uuid4().hex[:8]}")
    store = PostgresVectorStore(dsn=DSN, table=table)
    rows = [
        {
            "eu_id": "nda::0",
            "vector": [1.0, 0.0, 0.0],
            "text": "The employee shall not disclose confidential information.",
            "document_id": "nda",
            "language": "en",
            "page": 1,
            "checksum": "abc",
            "raw_uri": "raw/abc",
        },
        {
            "eu_id": "cats::0",
            "vector": [0.0, 1.0, 0.0],
            "text": "Cats are small domestic animals.",
            "document_id": "cats",
            "language": "en",
            "page": -1,
            "checksum": "def",
            "raw_uri": "raw/def",
        },
    ]
    try:
        store.upsert(rows)

        hits = store.search([1.0, 0.0, 0.0], limit=1)
        assert hits[0]["eu_id"] == "nda::0"
        assert hits[0]["_distance"] < 0.01

        text_hits = store.search_text("confidential disclose", limit=2)
        assert text_hits and text_hits[0]["eu_id"] == "nda::0"

        assert len(store.scan()) == 2
        store.upsert(rows)  # idempotent
        assert len(store.scan()) == 2
    finally:
        conn = store._connection()
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
