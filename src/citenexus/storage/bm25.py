"""``Bm25TextSearch`` — the in-core ``TextSearch`` implementation (spec §10).

Text search is its own store seam, symmetric with ``VectorStore``: Postgres
implements it natively (``tsvector``), and THIS is what LanceDB — or any store
that can ``scan()`` — uses. It scores the leaf's scanned rows with classic BM25
over a language-agnostic tokenizer (lowercase ``[a-z0-9]+``, **no** stemming,
**no** stopword list, §11a-safe) and returns the same ``_text_score``-carrying
row shape as every other ``TextSearch`` backend, so the lexical retriever has
exactly one code path.

> Honest scope: a lexical bag-of-terms signal, not BGE-M3's learned sparse
> weights — that needs a sparse-capable embedding endpoint and is a future
> upgrade. In-memory scoring is fine at leaf scale; a backend with a real text
> index (Postgres, Elasticsearch, Tantivy) implements ``TextSearch`` natively.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, Any

from citenexus.testing.fakes import tokenize

if TYPE_CHECKING:
    from citenexus.storage.protocols import VectorStore

# Standard BM25 saturation / length-normalization constants.
_K1 = 1.5
_B = 0.75


class Bm25TextSearch:
    """BM25-lite ranking over a scan-capable store's rows."""

    plugin_version = "bm25-text-search-v1"

    def __init__(self, store: VectorStore) -> None:
        self._store = store

    def search_text(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Rows ranked by BM25 against ``query`` (each with ``_text_score``)."""
        rows = self._store.scan()
        if not rows:
            return []
        terms = tokenize(query)
        if not terms:
            return []

        tokenized = [tokenize(str(row.get("text", ""))) for row in rows]
        n_docs = len(rows)
        avg_len = sum(len(toks) for toks in tokenized) / n_docs or 1.0

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
        return [{**rows[idx], "_text_score": score} for score, idx in scored[:limit]]
