"""The sparse / lexical retrieval signal — BM25-lite (spec §10).

``LexicalRetriever`` scans every EU text in the leaf and scores it with classic
BM25 over a language-agnostic tokenizer: lowercase ``[a-z0-9]+`` with **no**
stemming and **no** stopword list, so non-English text is never penalized
(multilingual-safe, §11a). A document containing a query term outranks one that
does not.

> Honest scope: this is a lexical bag-of-terms signal, not BGE-M3's learned
> sparse weights. Real sparse retrieval needs a sparse-capable embedding endpoint
> and is a future upgrade; BM25-lite is the deterministic v0.1 stand-in.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING

from trustrag.plugins.base import RetrieverPlugin
from trustrag.retrieve.types import Candidate, RetrievalSignal
from trustrag.testing.fakes import tokenize

if TYPE_CHECKING:
    from typing import Any

    from trustrag.storage.lance_store import LeafVectorStore

# Standard BM25 saturation / length-normalization constants.
_K1 = 1.5
_B = 0.75


def _page(value: object) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    return None


class LexicalRetriever(RetrieverPlugin):
    """BM25-lite lexical retrieval over the leaf's scanned texts."""

    plugin_version = "lexical-bm25-lite-v1"

    def __init__(self, store: LeafVectorStore) -> None:
        self._store = store

    def retrieve(self, query: str, k: int) -> list[Candidate]:
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
        doc_freq = {
            term: sum(1 for toks in tokenized if term in toks) for term in query_terms
        }

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
                norm = tf * (_K1 + 1.0) / (
                    tf + _K1 * (1.0 - _B + _B * doc_len / avg_len)
                )
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
                )
            )
        return candidates
