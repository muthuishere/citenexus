"""Per-leaf LanceDB vector store, hermetic on a local path (spec §6b)."""

from pathlib import Path

from citenexus.storage.lance_store import LanceVectorStore


def _rows() -> list[dict[str, object]]:
    return [
        {"eu_id": "eu_1", "vector": [0.1, 0.2, 0.3], "text": "near"},
        {"eu_id": "eu_2", "vector": [0.9, 0.8, 0.7], "text": "far"},
    ]


def test_upsert_then_search(tmp_path: Path) -> None:
    store = LanceVectorStore(str(tmp_path / "leafA"))
    store.upsert(_rows())
    hits = store.search([0.1, 0.2, 0.3], limit=1)
    assert len(hits) == 1
    assert hits[0]["eu_id"] == "eu_1"


def test_upsert_is_idempotent(tmp_path: Path) -> None:
    store = LanceVectorStore(str(tmp_path / "leafA"))
    store.upsert(_rows())
    store.upsert(_rows())  # same eu_ids — merge, not duplicate
    hits = store.search([0.9, 0.8, 0.7], limit=10)
    assert sorted(h["eu_id"] for h in hits) == ["eu_1", "eu_2"]


def test_leaves_are_isolated(tmp_path: Path) -> None:
    a = LanceVectorStore(str(tmp_path / "leafA"))
    b = LanceVectorStore(str(tmp_path / "leafB"))
    a.upsert(_rows())
    b.upsert(_rows())
    a.drop()
    assert a.search([0.1, 0.2, 0.3], limit=1) == []
    assert len(b.search([0.1, 0.2, 0.3], limit=1)) == 1


def test_search_empty_leaf_returns_empty(tmp_path: Path) -> None:
    store = LanceVectorStore(str(tmp_path / "leafEmpty"))
    assert store.search([0.0, 0.0, 0.0]) == []
