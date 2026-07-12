"""The rerank seam — an OpenAI-compatible cross-encoder reranker (spec §10).

``OpenAICompatibleReranker`` reorders fused candidates by posting
``{model, query, documents}`` to ``{base_url}/rerank`` and reading the endpoint's
per-document relevance scores (the Cohere/Jina/infinity ``results`` shape). The
HTTP call goes through an **injected** ``transport`` so unit tests stay hermetic;
the default transport uses stdlib ``urllib.request`` and adds no dependency. This
plugin is integration-only — hermetic tests use ``FakeReranker`` (identity).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from citenexus.http import DEFAULT_TRANSPORT, Transport
from citenexus.plugins.base import RerankerPlugin
from citenexus.retrieve.types import Candidate


class OpenAICompatibleReranker(RerankerPlugin):
    """Cross-encoder rerank over an injected, OpenAI-compatible endpoint."""

    plugin_version = "openai-rerank-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        transport: Transport | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._transport = transport or DEFAULT_TRANSPORT
        # First-class auth/provider headers (toolnexus style): ``${ENV}`` templates
        # resolved by the transport at call time, never held as values here.
        self._extra_headers = dict(headers or {})

    def _headers(self) -> dict[str, str]:
        # Wire clients speak JSON + any caller-supplied auth/provider headers
        # (``${ENV}`` templates, resolved by the transport at call time).
        return {"Content-Type": "application/json", **self._extra_headers}

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        items = list(candidates)
        if not items:
            return []

        body = json.dumps(
            {
                "model": self._model,
                "query": query,
                "documents": [c.text or "" for c in items],
            }
        ).encode("utf-8")
        raw = self._transport(f"{self._base_url}/rerank", body, self._headers())
        results = json.loads(raw).get("results", [])

        # Order by descending relevance; each result points back by `index`.
        ordered = sorted(results, key=lambda r: r.get("relevance_score", 0.0), reverse=True)
        reranked = [items[r["index"]] for r in ordered if 0 <= r["index"] < len(items)]
        # Append any candidate the endpoint omitted, preserving input order.
        seen = {id(c) for c in reranked}
        reranked.extend(c for c in items if id(c) not in seen)
        return reranked
