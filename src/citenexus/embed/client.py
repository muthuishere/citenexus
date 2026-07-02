"""``OpenAICompatibleEmbedding`` — a concrete dense ``EmbeddingPlugin`` (§4b).

CiteNexus bundles no models: embeddings come from an injected, OpenAI-compatible
endpoint (local Ollama ``bge-m3``, FlagEmbedding / infinity, …). This plugin
calls ``POST {base_url}/embeddings`` with ``{"model": ..., "input": [texts...]}``
and parses ``data[].embedding`` into dense ``list[list[float]]`` vectors.

The HTTP call is injected via a ``transport`` callable so unit tests stay
hermetic (a fake transport returns canned JSON — no network). The DEFAULT
transport is a tiny stdlib ``urllib.request`` wrapper, so there is no new
dependency.

Honest scope: this returns DENSE vectors only. BGE-M3 *sparse* term weights need
a sparse-capable endpoint and are handled by a separate lexical signal (BM25-lite
over stored EU text) — this plugin never fakes a sparse vector.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence

from citenexus.http import DEFAULT_TRANSPORT, Transport
from citenexus.plugins.base import EmbeddingPlugin

# (url, json body, headers) -> response bytes. The single seam that lets unit
# tests run hermetically while the default wires stdlib urllib.


class OpenAICompatibleEmbedding(EmbeddingPlugin):
    """Dense embeddings over an OpenAI-compatible ``/embeddings`` endpoint."""

    plugin_version = "openai-embed-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_env: str | None = None,
        extra_headers: dict[str, str] | None = None,
        transport: Transport | None = None,
    ) -> None:
        # Store only the env-var *name*, never the secret value.
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key_env = api_key_env
        self._extra_headers = dict(extra_headers or {})
        self._transport: Transport = transport or DEFAULT_TRANSPORT

    @property
    def _endpoint(self) -> str:
        return f"{self._base_url}/embeddings"

    def _headers(self) -> dict[str, str]:
        headers = {**self._extra_headers, "Content-Type": "application/json"}
        if self._api_key_env:
            # Read the key at call time; carry it ONLY in the Authorization
            # header. The value never lands on ``self`` and is never logged.
            key = os.environ.get(self._api_key_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts`` into dense vectors, preserving input order."""
        body = json.dumps({"model": self._model, "input": list(texts)}).encode("utf-8")
        raw = self._transport(self._endpoint, body, self._headers())
        payload = json.loads(raw)
        return [[float(x) for x in item["embedding"]] for item in payload["data"]]

    def embed_query(self, text: str) -> list[float]:
        """Embed a single text — the ingest ``Embedder`` convenience."""
        return self.embed([text])[0]
