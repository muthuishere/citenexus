"""EN query reformulation for dual-query retrieval (spec §10 / §11a).

Cross-lingual retrieval misses are a top abstention cause: a French query over
English evidence aligns imperfectly in embedding space and shares zero BM25
tokens. The researched fix (tRAG / RAG-Fusion): rewrite the query in English
with a SMALL model, retrieve with BOTH the original and the reformulation, and
RRF-fuse the lists. The original query is always kept — translation can damage
exact tokens (names, IDs, clause numbers) that lexical retrieval needs.

The instance carries a **shared reformulation cache** keyed by query, so
``ask()``, ``retrieve()``, and ``evaluate()`` (which asks per CSV row) pay the
model at most once per distinct question — including caching failures, so a dead
endpoint is not hammered.

Enhancement-only: any failure, an empty reply, or a reformulation identical to
the original returns ``None`` and retrieval proceeds single-query.
"""

from __future__ import annotations

import json
from typing import Protocol

from citenexus.http import DEFAULT_TRANSPORT, Transport


class Reformulator(Protocol):
    """The reformulation seam — structural, so test fakes satisfy it too."""

    def reformulate(self, query: str) -> str | None: ...


_PROMPT = (
    "Rewrite the following search query in English for retrieving documents. "
    "Keep names, numbers, and technical identifiers exactly as written. "
    "Reply with ONLY the rewritten query, nothing else.\n\n"
    "Query: {query}"
)


class QueryReformulator:
    """Rewrite a query in English via a small injected model, with a cache."""

    plugin_version = "query-reformulator-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._transport: Transport = transport or DEFAULT_TRANSPORT
        # The shared reformulation cache: query -> reformulation (or None).
        self._cache: dict[str, str | None] = {}

    def _headers(self) -> dict[str, str]:
        # Auth + provider headers are the ENDPOINT layer's job (HttpEndpoint
        # transport); wire clients only speak JSON.
        return {"Content-Type": "application/json"}

    def reformulate(self, query: str) -> str | None:
        """The EN reformulation of ``query`` — or ``None`` when it adds nothing."""
        if query in self._cache:
            return self._cache[query]
        result = self._reformulate_uncached(query)
        self._cache[query] = result
        return result

    def _reformulate_uncached(self, query: str) -> str | None:
        request = {
            "model": self._model,
            "messages": [{"role": "user", "content": _PROMPT.format(query=query)}],
            "temperature": 0.0,
        }
        body = json.dumps(request).encode("utf-8")
        try:
            raw = self._transport(f"{self._base_url}/chat/completions", body, self._headers())
            content: str = json.loads(raw)["choices"][0]["message"]["content"]
        except Exception:
            return None
        rewritten = content.strip()
        if not rewritten or rewritten == query:
            return None
        return rewritten
