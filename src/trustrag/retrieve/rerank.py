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
import os
import urllib.request
from collections.abc import Callable, Sequence

from trustrag.plugins.base import RerankerPlugin
from trustrag.retrieve.types import Candidate

# (url, json body, headers) -> response bytes.
Transport = Callable[[str, bytes, dict[str, str]], bytes]


def _urllib_transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request) as response:
        data: bytes = response.read()
    return data


class OpenAICompatibleReranker(RerankerPlugin):
    """Cross-encoder rerank over an injected, OpenAI-compatible endpoint."""

    plugin_version = "openai-rerank-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        transport: Transport | None = None,
        api_key_env: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._transport = transport or _urllib_transport
        self._api_key_env = api_key_env

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key_env:
            key = os.environ.get(self._api_key_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return headers

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
        ordered = sorted(
            results, key=lambda r: r.get("relevance_score", 0.0), reverse=True
        )
        reranked = [items[r["index"]] for r in ordered if 0 <= r["index"] < len(items)]
        # Append any candidate the endpoint omitted, preserving input order.
        seen = {id(c) for c in reranked}
        reranked.extend(c for c in items if id(c) not in seen)
        return reranked
