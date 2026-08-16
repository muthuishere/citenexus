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
from collections.abc import Mapping, Sequence

from citenexus.contracts import EmbeddingProvider, Vector
from citenexus.embed.batcher import DEFAULT_BATCH_SIZE, embed_in_batches
from citenexus.http import DEFAULT_TRANSPORT, Transport
from citenexus.plugins.base import EmbeddingPlugin

# (url, json body, headers) -> response bytes. The single seam that lets unit
# tests run hermetically while the default wires stdlib urllib.


class OpenAICompatibleEmbedding(EmbeddingPlugin, EmbeddingProvider):
    """Dense embeddings over an OpenAI-compatible ``/embeddings`` endpoint.

    Declares the published ``EmbeddingProvider`` contract (ADR-0014): ``embed_many``
    is the batch primitive and the method the pipeline actually calls. The
    ``EmbeddingPlugin`` ABC stays on the class so registry-based callers keep
    working (0.x policy: deprecated-not-removed).
    """

    plugin_version = "openai-embed-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        transport: Transport | None = None,
        headers: Mapping[str, str] | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._batch_size = batch_size
        self._transport: Transport = transport or DEFAULT_TRANSPORT
        # First-class auth/provider headers (toolnexus style): put
        # ``{"Authorization": "Bearer ${API_KEY}"}`` here — the ``${ENV}`` value
        # is expanded at the request boundary, never held on this object.
        self._extra_headers = dict(headers or {})

    @property
    def _endpoint(self) -> str:
        return f"{self._base_url}/embeddings"

    def _headers(self) -> dict[str, str]:
        # Wire clients speak JSON + any caller-supplied auth/provider headers
        # (``${ENV}`` templates, resolved by the transport at call time).
        return {"Content-Type": "application/json", **self._extra_headers}

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        """ONE request for ``texts`` — the ``EmbeddingPlugin`` / `SequenceEmbedder`
        shape. Prefer `embed_many`, which splits oversized inputs into batches."""
        if not texts:
            return []
        body = json.dumps({"model": self._model, "input": list(texts)}).encode("utf-8")
        raw = self._transport(self._endpoint, body, self._headers())
        payload = json.loads(raw)
        return [[float(x) for x in item["embedding"]] for item in payload["data"]]

    def embed_many(self, texts: Sequence[str]) -> list[Vector]:
        """The `EmbeddingProvider` contract: every text, in order, batched.

        One request per ``batch_size`` texts. This is the method ingest and the
        vector retriever call; ``embed`` is the single-request primitive it is
        built from.
        """
        return embed_in_batches(self, texts, self._batch_size)

    def embed_query(self, text: str) -> Vector:
        """DEPRECATED: embed a single text. Use ``embed_many([text])[0]``."""
        return self.embed([text])[0]
