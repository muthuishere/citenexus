"""The sparse / lexical retrieval signal (spec §10).

Two paths, one retriever:

- **Native** — when the store also implements the ``TextSearch`` protocol
  (Postgres ``tsvector``), the backend ranks text itself: indexed, scalable,
  language-agnostic (``'simple'`` config, no stemming).
- **BM25-lite fallback** — for stores that can't (LanceDB): scan every EU text
  and score with classic BM25 over a language-agnostic tokenizer (lowercase
  ``[a-z0-9]+``, no stemming, no stopword list, §11a-safe).

> Honest scope: neither path is BGE-M3's learned sparse weights. Real sparse
> retrieval needs a sparse-capable embedding endpoint and is a future upgrade.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING

from trustrag.plugins.base import RetrieverPlugin
from trustrag.retrieve.types import Candidate, RetrievalSignal
from trustrag.storage.protocols import TextSearch
from trustrag.testing.fakes import tokenize

if TYPE_CHECKING:
    from typing import Any

    from trustrag.storage.protocols import VectorStore

# Standard BM25 saturation / length-normalization constants.
_K1 = 1.5
_B = 0.75


def _page(value: object) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    return None


class LexicalRetriever(RetrieverPlugin):
    """Lexical retrieval: native backend text search, else BM25-lite over scan."""

    plugin_version = "lexical-bm25-lite-v1"

    def __init__(self, store: VectorStore) -> None:
        self._store = store

    def retrieve(self, query: str, k: int) -> list[Candidate]:
        if isinstance(self._store, TextSearch):
            return self._native(query, k)
        rows = self._store.scan()
        if not rows:
            return []

        terms = tokenize(query)
        if not terms:
            return []

        tokenized = [tokenize(str(row.get("text", ""))) for row in rows]
        n_docs = len(rows)
        avg_len = sum(len(toks) for toks in tokenized) / n_docs or 1.0

        # Document frequency per query term.
        query_terms = set(terms)
        doc_freq = {term: sum(1 for toks in tokenized if term in toks) for term in query_terms}

        scored: list[tuple[float, int]] = []
        for idx, toks in enumerate(tokenized):
            counts = Counter(toks)
            doc_len = len(toks)
            score = 0.0
            for term in query_terms:
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                n_t = doc_freq[term]
                idf = math.log(1.0 + (n_docs - n_t + 0.5) / (n_t + 0.5))
                norm = tf * (_K1 + 1.0) / (tf + _K1 * (1.0 - _B + _B * doc_len / avg_len))
                score += idf * norm
            if score > 0.0:
                scored.append((score, idx))

        # Descending score; stable tie-break by original row order.
        scored.sort(key=lambda pair: (-pair[0], pair[1]))

        candidates: list[Candidate] = []
        for score, idx in scored[:k]:
            row: dict[str, Any] = rows[idx]
            candidates.append(
                Candidate(
                    eu_id=str(row["eu_id"]),
                    score=score,
                    signal=RetrievalSignal.lexical,
                    document_id=row.get("document_id"),
                    text=row.get("text"),
                    page=_page(row.get("page")),
                    language=row.get("language"),
                    checksum=row.get("checksum"),
                    raw_uri=row.get("raw_uri"),
                )
            )
        return candidates

    def _native(self, query: str, k: int) -> list[Candidate]:
        """Delegate ranking to the backend's own text search (``TextSearch``)."""
        assert isinstance(self._store, TextSearch)
        candidates: list[Candidate] = []
        for row in self._store.search_text(query, limit=k):
            candidates.append(
                Candidate(
                    eu_id=str(row["eu_id"]),
                    score=float(row.get("_text_score", 0.0)),
                    signal=RetrievalSignal.lexical,
                    document_id=row.get("document_id"),
                    text=row.get("text"),
                    page=_page(row.get("page")),
                    language=row.get("language"),
                    checksum=row.get("checksum"),
                    raw_uri=row.get("raw_uri"),
                )
            )
        return candidates
