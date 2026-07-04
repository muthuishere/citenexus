"""Wiki-navigation retrieval signal resolved down to Evidence Units."""

from __future__ import annotations

from typing import Any

from citenexus.answer.verify import content_tokens
from citenexus.plugins.base import RetrieverPlugin
from citenexus.retrieve.types import Candidate, RetrievalSignal
from citenexus.storage.protocols import VectorStore
from citenexus.wiki.store import WikiStore


def _page(value: object) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    return None


class WikiRetriever(RetrieverPlugin):
    """Navigate wiki pages, then return the citable EUs under matched pages."""

    plugin_version = "wiki-retriever-v2"

    def __init__(self, wiki_store: WikiStore, leaf_store: VectorStore) -> None:
        self._wiki_store = wiki_store
        self._leaf_store = leaf_store

    def retrieve(self, query: str, k: int) -> list[Candidate]:
        terms = content_tokens(query)
        if not terms:
            return []

        # 1) Match against the LIGHT index only (one small S3 object) — the
        #    wiki is never loaded wholesale, so query cost stays flat at scale.
        page_scores: dict[str, float] = {}
        for entry in self._wiki_store.load_index():
            haystack = (
                {str(keyword) for keyword in entry.get("keywords", ())}
                | content_tokens(str(entry.get("title", "")))
                | content_tokens(str(entry.get("summary", "")))
            )
            hits = len(terms & haystack)
            if hits == 0:
                continue
            page_id = str(entry["page_id"])
            page_scores[page_id] = max(page_scores.get(page_id, 0.0), float(hits))
            # Navigate one hop: a matched page also vouches for the pages it
            # [[links]] to, at half its own hit score. Still resolves to EUs —
            # the linked page itself is never a candidate, let alone a citation.
            for link in entry.get("links", ()):
                link_id = str(link)
                page_scores[link_id] = max(page_scores.get(link_id, 0.0), hits / 2.0)
        if not page_scores:
            return []

        # 2) Fetch ONLY the matched pages to collect their EU refs.
        eu_scores: dict[str, float] = {}
        for page_id, score in page_scores.items():
            page = self._wiki_store.load_page(page_id)
            if page is None:
                continue
            for eu_ref in page.eu_refs:
                eu_scores[eu_ref] = max(eu_scores.get(eu_ref, 0.0), score)
        if not eu_scores:
            return []

        rows_by_id: dict[str, dict[str, Any]] = {
            str(row["eu_id"]): row for row in self._leaf_store.scan()
        }
        candidates: list[Candidate] = []
        for eu_id, score in sorted(eu_scores.items(), key=lambda item: (-item[1], item[0])):
            row = rows_by_id.get(eu_id)
            if row is None:
                continue
            candidates.append(
                Candidate(
                    eu_id=eu_id,
                    score=score,
                    signal=RetrievalSignal.wiki,
                    document_id=row.get("document_id"),
                    text=row.get("text"),
                    page=_page(row.get("page")),
                    language=row.get("language"),
                    checksum=row.get("checksum"),
                    raw_uri=row.get("raw_uri"),
                )
            )
        return candidates[:k]
