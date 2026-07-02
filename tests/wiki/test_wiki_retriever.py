"""Wiki navigation resolves page hits down to cited Evidence Units."""

from __future__ import annotations

from pathlib import Path

from trustrag.domain.partition import PartitionPath
from trustrag.retrieve.types import RetrievalSignal
from trustrag.storage.backend import LocalFsBackend
from trustrag.storage.lance_store import LanceVectorStore
from trustrag.testing import FakeEmbedding
from trustrag.wiki import WikiRetriever, WikiStore


def test_wiki_retriever_returns_underlying_eu(tmp_path: Path) -> None:
    partition = PartitionPath.of(("org", "acme"))
    backend = LocalFsBackend(tmp_path / "objects")
    store = LanceVectorStore(str(tmp_path / "leaf"))
    embedder = FakeEmbedding()
    store.upsert(
        [
            {
                "eu_id": "handbook::0",
                "vector": embedder.embed("Remote work approval policy"),
                "text": "Remote work approval policy",
                "document_id": "handbook",
                "language": "en",
                "page": -1,
                "checksum": "def",
                "raw_uri": "raw/def",
            }
        ]
    )
    wiki_store = WikiStore(backend, partition)
    pages = wiki_store.build_from_store(store)

    assert pages[0].page_id == "wiki:handbook"
    out = WikiRetriever(wiki_store, store).retrieve("approval policy", k=3)
    assert out[0].eu_id == "handbook::0"
    assert out[0].signal is RetrievalSignal.wiki
    assert out[0].checksum == "def"
