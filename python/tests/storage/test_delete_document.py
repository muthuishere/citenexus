"""``VectorStore.delete_document`` — the row-level inverse of ingest (document-revoke).

The reference LanceDB backend removes exactly one document's rows, leaves every
other document intact, and is a no-op on unknown ids / a leaf with no table yet.
Because the in-core BM25 lexical index is derived from the same rows, a lexical
query stops matching the removed document once its rows are gone — no separate
text-search deletion.
"""

from __future__ import annotations

from pathlib import Path

from citenexus.storage.lance_store import LanceTextSearch, LanceVectorStore


def _row(eu_id: str, vec: list[float], text: str, doc: str) -> dict[str, object]:
    return {"eu_id": eu_id, "vector": vec, "text": text, "document_id": doc}


def _rows() -> list[dict[str, object]]:
    return [
        _row("nda::0", [0.1, 0.2, 0.3], "confidential disclosure", "nda"),
        _row("nda::1", [0.2, 0.1, 0.4], "secret information", "nda"),
        _row("leave::0", [0.9, 0.8, 0.7], "annual leave policy", "leave"),
    ]


def test_delete_document_removes_only_that_documents_rows(tmp_path: Path) -> None:
    store = LanceVectorStore(str(tmp_path / "leaf"))
    store.upsert(_rows())
    store.delete_document("nda")
    assert {r["eu_id"] for r in store.scan()} == {"leave::0"}


def test_delete_unknown_document_is_a_noop(tmp_path: Path) -> None:
    store = LanceVectorStore(str(tmp_path / "leaf"))
    store.upsert(_rows())
    store.delete_document("does-not-exist")
    assert len(store.scan()) == 3


def test_delete_before_table_exists_is_a_noop(tmp_path: Path) -> None:
    store = LanceVectorStore(str(tmp_path / "empty"))
    store.delete_document("nda")  # no table yet — must not raise
    assert store.scan() == []


def test_delete_escapes_single_quotes(tmp_path: Path) -> None:
    store = LanceVectorStore(str(tmp_path / "leaf"))
    store.upsert(
        [
            _row("x::0", [0.1, 0.2, 0.3], "a", "o'brien v. acme"),
            _row("y::0", [0.4, 0.5, 0.6], "b", "smith"),
        ]
    )
    store.delete_document("o'brien v. acme")
    assert {r["eu_id"] for r in store.scan()} == {"y::0"}


def test_lexical_index_reflects_deletion(tmp_path: Path) -> None:
    store = LanceVectorStore(str(tmp_path / "leaf"))
    store.upsert(_rows())
    text = LanceTextSearch(store)
    assert any(h["document_id"] == "nda" for h in text.search_text("confidential"))
    store.delete_document("nda")
    assert not any(h["document_id"] == "nda" for h in text.search_text("confidential"))
