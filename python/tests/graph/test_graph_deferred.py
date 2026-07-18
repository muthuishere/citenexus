"""Deferred graph rebuild — a single ingest marks the graph dirty; the read path
rebuilds lazily (structural-code-graph, group 4).

The batch path already amortizes via refresh_slow_path(); this closes the
single-`ingest()`-full-rebuilds-every-call gap.
"""

from __future__ import annotations

from pathlib import Path

from citenexus.domain.partition import PartitionPath
from citenexus.graph import GraphRetriever, GraphStore
from citenexus.storage.backend import LocalFsBackend
from citenexus.storage.lance_store import LanceVectorStore
from citenexus.testing import FakeEmbedding


def _store(tmp_path: Path) -> tuple[LocalFsBackend, LanceVectorStore]:
    backend = LocalFsBackend(tmp_path / "objects")
    store = LanceVectorStore(str(tmp_path / "leaf"))
    embedder = FakeEmbedding()
    store.upsert(
        [
            {
                "eu_id": "nda::0",
                "vector": embedder.embed("Confidential disclosure obligations"),
                "text": "Confidential disclosure obligations",
                "document_id": "nda",
                "language": "en",
                "page": -1,
                "checksum": "abc",
                "raw_uri": "raw/abc",
            }
        ]
    )
    return backend, store


def test_mark_dirty_does_not_build(tmp_path: Path) -> None:
    backend, _store_unused = _store(tmp_path)
    gs = GraphStore(backend, PartitionPath.of(("org", "acme")))
    gs.mark_dirty()
    # Nothing built yet — no artifact on disk.
    assert gs.load() is None


def test_ensure_current_rebuilds_when_dirty(tmp_path: Path) -> None:
    backend, store = _store(tmp_path)
    gs = GraphStore(backend, PartitionPath.of(("org", "acme")))
    gs.mark_dirty()
    gs.ensure_current(store)
    index = gs.load()
    assert index is not None and index.nodes


def test_ensure_current_is_noop_when_clean(tmp_path: Path) -> None:
    backend, store = _store(tmp_path)
    gs = GraphStore(backend, PartitionPath.of(("org", "acme")))
    gs.build_from_store(store)  # clears dirty
    # Mutate the underlying store AFTER a clean build; ensure_current must NOT
    # rebuild (still clean), so the graph does not pick up the new row.
    embedder = FakeEmbedding()
    store.upsert(
        [
            {
                "eu_id": "nda::1",
                "vector": embedder.embed("unrelated novel token zzzznewword"),
                "text": "unrelated novel token zzzznewword",
                "document_id": "nda",
                "language": "en",
                "page": -1,
                "checksum": "def",
                "raw_uri": "raw/def",
            }
        ]
    )
    gs.ensure_current(store)
    labels = {n.label for n in (gs.load() or _empty()).nodes}
    assert "zzzznewword" not in labels  # not rebuilt → new token absent


def test_read_after_dirty_sees_consistent_graph(tmp_path: Path) -> None:
    backend, store = _store(tmp_path)
    gs = GraphStore(backend, PartitionPath.of(("org", "acme")))
    gs.mark_dirty()  # as a single ingest would
    # The read path rebuilds lazily, so the retriever sees a current graph.
    out = GraphRetriever(gs, store).retrieve("disclosure", k=3)
    assert out and out[0].eu_id == "nda::0"


def test_build_from_store_clears_dirty(tmp_path: Path) -> None:
    backend, store = _store(tmp_path)
    gs = GraphStore(backend, PartitionPath.of(("org", "acme")))
    gs.mark_dirty()
    gs.build_from_store(store)  # a full rebuild must clear the dirty marker
    # A subsequent ensure_current is a no-op: mutate then confirm no rebuild.
    embedder = FakeEmbedding()
    store.upsert(
        [
            {
                "eu_id": "nda::2",
                "vector": embedder.embed("another zzzsecond marker word"),
                "text": "another zzzsecond marker word",
                "document_id": "nda",
                "language": "en",
                "page": -1,
                "checksum": "ghi",
                "raw_uri": "raw/ghi",
            }
        ]
    )
    gs.ensure_current(store)
    labels = {n.label for n in (gs.load() or _empty()).nodes}
    assert "zzzsecond" not in labels


def _empty() -> object:
    from citenexus.graph.store import GraphIndex

    return GraphIndex(nodes=(), edges=())
