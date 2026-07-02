"""Graph artifacts and retrieval resolve back to Evidence Units."""

from __future__ import annotations

from pathlib import Path

from citenexus.domain.partition import PartitionPath
from citenexus.graph import GraphRetriever, GraphStore
from citenexus.retrieve.types import RetrievalSignal
from citenexus.storage.backend import LocalFsBackend
from citenexus.storage.lance_store import LanceVectorStore
from citenexus.testing import FakeEmbedding


def test_graph_build_and_retrieve_resolves_to_eu(tmp_path: Path) -> None:
    partition = PartitionPath.of(("org", "acme"))
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
    graph_store = GraphStore(backend, partition)
    index = graph_store.build_from_store(store)

    assert index.nodes
    out = GraphRetriever(graph_store, store).retrieve("disclosure", k=3)
    assert out[0].eu_id == "nda::0"
    assert out[0].signal is RetrievalSignal.graph
    assert out[0].raw_uri == "raw/abc"
