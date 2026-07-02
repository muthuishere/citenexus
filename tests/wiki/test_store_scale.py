"""S3-scalable wiki layout — per-page objects, light index, incremental growth.

At "very big" corpus scale, one pages.json blob + full-wiki rebuilds + load-all
retrieval all break. The scalable layout keeps a LIGHT index manifest (no
eu_refs) that queries read, per-page JSON objects fetched only when matched,
incremental per-document integration (no full rebuild on ingest), and an
append-only log.md — all through the StorageBackend (S3-native).
"""

from __future__ import annotations

from pathlib import Path

from citenexus.domain.partition import PartitionPath
from citenexus.storage.backend import LocalFsBackend
from citenexus.storage.lance_store import LanceVectorStore
from citenexus.testing import FakeEmbedding
from citenexus.wiki.store import WikiPage, WikiStore

PART = PartitionPath.of(("workspace", "w1"))


def _seeded_store(tmp_path: Path, docs: dict[str, str]) -> LanceVectorStore:
    store = LanceVectorStore(str(tmp_path / "leaf"))
    embedder = FakeEmbedding()
    rows = []
    for doc_id, text in docs.items():
        rows.append(
            {
                "eu_id": f"{doc_id}::0::0",
                "vector": embedder.embed(text),
                "text": text,
                "document_id": doc_id,
                "language": "en",
                "page": -1,
                "checksum": "c",
                "raw_uri": "raw/c",
            }
        )
    store.upsert(rows)
    return store


def test_per_page_objects_and_light_index(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path / "objects")
    store = _seeded_store(tmp_path, {"nda": "Employees shall not disclose secrets."})
    wiki = WikiStore(backend, PART)
    pages = wiki.build_from_store(store)
    assert pages

    # light index exists and carries NO eu_refs (stays small at scale)
    index = backend.get_json(wiki.index_json_key)
    assert index and "eu_refs" not in index[0]
    assert {"page_id", "title", "keywords", "links", "summary"} <= set(index[0])

    # the full page is its own object, fetched individually
    page = wiki.load_page(pages[0].page_id)
    assert page is not None
    assert page.eu_refs == ("nda::0::0",)


def test_integrate_document_is_incremental(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path / "objects")
    store = _seeded_store(
        tmp_path,
        {"nda": "Employees shall not disclose secrets.", "hr": "Leave accrues monthly."},
    )
    wiki = WikiStore(backend, PART)
    wiki.integrate_document("nda", store)
    assert {e["page_id"] for e in backend.get_json(wiki.index_json_key)} == {"wiki:nda"}

    # integrating the second document ADDS a page without touching the first
    first_before = wiki.load_page("wiki:nda")
    wiki.integrate_document("hr", store)
    index_ids = {e["page_id"] for e in backend.get_json(wiki.index_json_key)}
    assert index_ids == {"wiki:nda", "wiki:hr"}
    assert wiki.load_page("wiki:nda") == first_before

    # re-integrating the same document upserts, never duplicates
    wiki.integrate_document("hr", store)
    assert len(backend.get_json(wiki.index_json_key)) == 2


def test_log_records_integrations(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path / "objects")
    store = _seeded_store(tmp_path, {"nda": "Employees shall not disclose secrets."})
    wiki = WikiStore(backend, PART)
    wiki.integrate_document("nda", store)
    wiki.build_from_store(store)
    log = backend.get_bytes(wiki.log_key).decode("utf-8")
    assert "ingest | nda" in log
    assert "rebuild |" in log
    # append-only: the earlier entry is still there
    assert log.index("ingest | nda") < log.index("rebuild |")


def test_legacy_pages_json_still_loads(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path / "objects")
    wiki = WikiStore(backend, PART)
    legacy = [
        {
            "page_id": "wiki:old",
            "title": "old",
            "summary": "s",
            "keywords": ["k"],
            "eu_refs": ["old::0"],
        }
    ]
    backend.put_json(wiki.key, legacy)  # the pre-scale single-blob layout
    pages = wiki.load()
    assert pages[0].page_id == "wiki:old"
    assert pages[0].links == ()


def test_retriever_fetches_only_matched_pages(tmp_path: Path) -> None:
    from citenexus.wiki.retrieve import WikiRetriever

    backend = LocalFsBackend(tmp_path / "objects")
    store = _seeded_store(
        tmp_path,
        {"nda": "Employees shall not disclose secrets.", "hr": "Leave accrues monthly."},
    )
    wiki = WikiStore(backend, PART)
    wiki.build_from_store(store)

    fetched: list[str] = []
    original = wiki.load_page

    def spying_load(page_id: str) -> WikiPage | None:
        fetched.append(page_id)
        return original(page_id)

    wiki.load_page = spying_load  # type: ignore[method-assign]
    out = WikiRetriever(wiki, store).retrieve("disclose secrets", k=3)
    assert out and out[0].document_id == "nda"
    # only the matched page (+ its links) was fetched — not the whole wiki
    assert "wiki:hr" not in fetched
