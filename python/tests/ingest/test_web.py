"""Web fetch + crawl for ingesting websites (spec §8 universal intake).

A site is just another source: fetch a URL (injected transport → hermetic), then
crawl same-domain links breadth-first, depth- and page-capped. The crawler yields
(url, html) pairs the HTML extractor already knows how to turn into EUs — no new
dependency (stdlib fetch + the bs4 already used by the extractor).
"""

from __future__ import annotations

from citenexus.ingest.web import CrawlResult, FetchTransport, crawl, fetch_url, is_url


def test_is_url_detects_http_and_https() -> None:
    assert is_url("https://example.com/page")
    assert is_url("http://example.com")
    assert not is_url("policy.pdf")
    assert not is_url("/local/path.txt")
    assert not is_url("s3://bucket/key")


def _pages() -> dict[str, str]:
    return {
        "https://site.test/": (
            "<html><body><h1>Home</h1>"
            "<a href='/a'>A</a><a href='https://site.test/b'>B</a>"
            "<a href='https://other.test/x'>Off-site</a></body></html>"
        ),
        "https://site.test/a": "<html><body><h1>Page A</h1><a href='/c'>C</a></body></html>",
        "https://site.test/b": "<html><body><h1>Page B</h1></body></html>",
        "https://site.test/c": "<html><body><h1>Page C</h1></body></html>",
    }


def _transport(pages: dict[str, str]) -> FetchTransport:
    def fetch(url: str) -> tuple[bytes, str]:
        if url not in pages:
            raise KeyError(url)
        return pages[url].encode("utf-8"), "text/html"

    return fetch


def test_fetch_url_returns_bytes_and_content_type() -> None:
    data, ctype = fetch_url("https://site.test/", transport=_transport(_pages()))
    assert b"Home" in data
    assert ctype == "text/html"


def test_crawl_follows_same_domain_links_bfs() -> None:
    results = crawl("https://site.test/", transport=_transport(_pages()), max_pages=10)
    urls = {r.url for r in results}
    # reached home + A + B + C (transitive), never the off-site link
    assert "https://site.test/" in urls
    assert "https://site.test/a" in urls
    assert "https://site.test/c" in urls
    assert not any("other.test" in u for u in urls)


def test_crawl_respects_max_pages() -> None:
    results = crawl("https://site.test/", transport=_transport(_pages()), max_pages=2)
    assert len(results) == 2


def test_crawl_respects_max_depth() -> None:
    # depth 0 = seed only
    results = crawl("https://site.test/", transport=_transport(_pages()), max_pages=10, max_depth=0)
    assert len(results) == 1
    assert results[0].url == "https://site.test/"


def test_crawl_result_carries_html() -> None:
    results = crawl("https://site.test/", transport=_transport(_pages()), max_pages=1)
    assert isinstance(results[0], CrawlResult)
    assert "Home" in results[0].html


def test_crawl_skips_unfetchable_pages() -> None:
    pages = _pages()
    del pages["https://site.test/a"]  # a link that 404s
    results = crawl("https://site.test/", transport=_transport(pages), max_pages=10)
    # crawl continues; the dead link is simply absent
    assert not any(r.url.endswith("/a") for r in results)
    assert any(r.url.endswith("/b") for r in results)
