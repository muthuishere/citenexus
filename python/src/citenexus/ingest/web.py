"""Web fetch + same-domain crawl for ingesting websites (spec §8).

Universal intake means a URL is just another source. This module fetches a URL
(through an injected ``transport`` so tests stay hermetic; the default is stdlib
urllib — no new dependency) and crawls same-domain links breadth-first, capped by
page count and depth. It yields ``CrawlResult(url, html)`` pairs that the HTML
extractor already turns into Evidence Units.

Scope guards for safety/politeness: only ``http(s)`` URLs, only the seed's
registered domain, deduped, and hard page/depth caps — a crawl can never wander
off-site or run unbounded.
"""

from __future__ import annotations

import urllib.request
from collections import deque
from collections.abc import Callable
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict

# url -> (body bytes, content-type). Injected so unit tests avoid the network.
FetchTransport = Callable[[str], tuple[bytes, str]]

DEFAULT_MAX_PAGES = 50
DEFAULT_MAX_DEPTH = 3


class CrawlResult(BaseModel):
    """One fetched page: its final URL and decoded HTML."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    html: str
    content_type: str = "text/html"


def is_url(source: object) -> bool:
    """True when ``source`` is an ``http(s)`` URL string."""
    if not isinstance(source, str):
        return False
    return urlparse(source).scheme in ("http", "https")


def _urllib_fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "citenexus"})
    with urllib.request.urlopen(request) as response:
        data: bytes = response.read()
        ctype = response.headers.get_content_type()
    return data, ctype


def fetch_url(url: str, *, transport: FetchTransport | None = None) -> tuple[bytes, str]:
    """Fetch ``url`` → (body bytes, content-type). Default transport is urllib."""
    return (transport or _urllib_fetch)(url)


def _links(html: str, base_url: str) -> list[str]:
    """Absolute, fragment-stripped links found in ``html``, in document order."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    for anchor in soup.find_all("a", href=True):
        absolute, _ = urldefrag(urljoin(base_url, str(anchor["href"])))
        if is_url(absolute):
            out.append(absolute)
    return out


def crawl(
    seed_url: str,
    *,
    transport: FetchTransport | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[CrawlResult]:
    """Breadth-first crawl of ``seed_url``'s domain, page- and depth-capped."""
    fetch = transport or _urllib_fetch
    domain = urlparse(seed_url).netloc
    seen: set[str] = set()
    results: list[CrawlResult] = []
    queue: deque[tuple[str, int]] = deque([(urldefrag(seed_url)[0], 0)])

    while queue and len(results) < max_pages:
        url, depth = queue.popleft()
        if url in seen or urlparse(url).netloc != domain:
            continue
        seen.add(url)
        try:
            data, ctype = fetch(url)
        except Exception:
            continue
        html = data.decode("utf-8", errors="replace")
        results.append(CrawlResult(url=url, html=html, content_type=ctype))
        if depth >= max_depth:
            continue
        for link in _links(html, url):
            if link not in seen:
                queue.append((link, depth + 1))
    return results
