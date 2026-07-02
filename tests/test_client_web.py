"""The public client ingests URLs and crawls websites (spec §8)."""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.testing import FakeEmbedding, FakeLLM

_PAGES = {
    "https://kb.test/": (
        "<html><body><h1>Leave policy</h1>"
        "<p>Employees accrue twenty days of paid leave per year.</p>"
        "<a href='/remote'>Remote</a></body></html>"
    ),
    "https://kb.test/remote": (
        "<html><body><h1>Remote work</h1>"
        "<p>Remote work requires manager approval in advance.</p></body></html>"
    ),
}


def _fetch(url: str) -> tuple[bytes, str]:
    return _PAGES[url].encode("utf-8"), "text/html"


def _rag(tmp_path: Path) -> CiteNexus:
    return CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        fetch_transport=_fetch,
    )


def test_ingest_url_fetches_and_indexes(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    result = rag.ingest("https://kb.test/")
    assert result.status == "ingested"
    # the fetched page's text is retrievable and cited to its URL
    hits = rag.retrieve("How many days of paid leave do employees accrue?")
    assert hits
    assert hits[0].document_id == "https://kb.test/"


def test_crawl_ingests_whole_site(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    results = rag.crawl("https://kb.test/", max_pages=10)
    assert len(results) == 2
    # a page reached only by following a link is retrievable
    hits = rag.retrieve("What does remote work require?")
    assert any(h.document_id == "https://kb.test/remote" for h in hits)


def test_local_path_still_ingests_normally(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    result = rag.ingest(text="A local plain text fact.", document_id="local")
    assert result.status == "ingested"
