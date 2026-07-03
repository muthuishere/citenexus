"""Wiki navigation resolves page hits down to cited Evidence Units."""

from __future__ import annotations

from pathlib import Path

from citenexus.domain.partition import PartitionPath
from citenexus.retrieve.types import RetrievalSignal
from citenexus.storage.backend import LocalFsBackend
from citenexus.storage.lance_store import LanceVectorStore
from citenexus.testing import FakeEmbedding
from citenexus.wiki import WikiPage, WikiRetriever, WikiStore


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


def _row(eu_id: str, text: str, document_id: str) -> dict[str, object]:
    return {
        "eu_id": eu_id,
        "vector": FakeEmbedding().embed(text),
        "text": text,
        "document_id": document_id,
        "language": "en",
        "page": -1,
        "checksum": f"sum-{eu_id}",
        "raw_uri": f"raw/{eu_id}",
    }


def test_linked_pages_contribute_eus_at_half_score(tmp_path: Path) -> None:
    """Navigate one hop: a matched page vouches for its [[links]]' EUs at hits/2."""
    partition = PartitionPath.of(("org", "acme"))
    backend = LocalFsBackend(tmp_path / "objects")
    store = LanceVectorStore(str(tmp_path / "leaf"))
    store.upsert(
        [
            _row("a::0", "Remote work needs manager approval.", "a"),
            _row("b::0", "Equipment stipend rules.", "b"),
        ]
    )
    wiki_store = WikiStore(backend, partition)
    wiki_store.save(
        (
            WikiPage(
                page_id="remote-work",
                title="Remote work",
                summary="Working remotely.",
                keywords=("remote", "work"),
                eu_refs=("a::0",),
                links=("equipment", "no-such-page"),
            ),
            WikiPage(
                page_id="equipment",
                title="Equipment",
                summary="Stipends.",
                keywords=("stipend",),
                eu_refs=("b::0",),
            ),
        )
    )

    out = WikiRetriever(wiki_store, store).retrieve("remote work", k=5)
    assert [(c.eu_id, c.score) for c in out] == [("a::0", 2.0), ("b::0", 1.0)]
    # Navigate-not-cite: every candidate carries the EU's own text/provenance,
    # never the wiki page's words — the page is a map, not a source.
    assert out[1].text == "Equipment stipend rules."
    assert out[1].checksum == "sum-b::0"
    assert out[1].signal is RetrievalSignal.wiki


def test_direct_hit_outranks_one_hop_contribution(tmp_path: Path) -> None:
    """An EU's direct page match wins over a weaker linked-page contribution."""
    partition = PartitionPath.of(("org", "acme"))
    backend = LocalFsBackend(tmp_path / "objects")
    store = LanceVectorStore(str(tmp_path / "leaf"))
    store.upsert([_row("a::0", "Remote work policy text.", "a")])
    wiki_store = WikiStore(backend, partition)
    wiki_store.save(
        (
            WikiPage(
                page_id="remote-work",
                title="Remote work",
                summary="",
                keywords=("remote", "work"),
                eu_refs=("a::0",),
            ),
            WikiPage(
                page_id="hub",
                title="Remote hub",
                summary="",
                keywords=("remote",),
                eu_refs=(),
                links=("remote-work",),
            ),
        )
    )
    out = WikiRetriever(wiki_store, store).retrieve("remote work", k=5)
    # Direct match scores 2 hits; the hub's one-hop 1/2 never lowers it.
    assert [(c.eu_id, c.score) for c in out] == [("a::0", 2.0)]
