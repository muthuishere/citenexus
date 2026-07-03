"""OpenAICompatibleEmbedding — dense vectors over an injected transport (§4b)."""

from __future__ import annotations

import json
import os
import socket
from urllib.parse import urlparse

import pytest

from citenexus.embed import OpenAICompatibleEmbedding


class RecordingTransport:
    """A hermetic fake transport: records the request, returns canned JSON.

    Signature matches ``Callable[[str, bytes, dict[str, str]], bytes]`` —
    (url, json body, headers) -> response bytes.
    """

    def __init__(self, dim: int = 4) -> None:
        self.dim = dim
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.calls.append((url, body, dict(headers)))
        payload = json.loads(body)
        inputs = payload["input"]
        # one distinct, deterministic dense vector per input, in order
        data = [{"embedding": [float(i)] * self.dim} for i, _ in enumerate(inputs)]
        return json.dumps({"data": data}).encode("utf-8")

    @property
    def last_body(self) -> dict[str, object]:
        body: dict[str, object] = json.loads(self.calls[-1][1])
        return body

    @property
    def last_headers(self) -> dict[str, str]:
        return self.calls[-1][2]


def _plugin(
    transport: RecordingTransport, api_key_env: str | None = None
) -> OpenAICompatibleEmbedding:
    return OpenAICompatibleEmbedding(
        base_url="http://embed.test/v1",
        model="bge-m3",
        transport=transport,
    )


def test_plugin_version() -> None:
    assert OpenAICompatibleEmbedding.plugin_version == "openai-embed-v1"


def test_embed_returns_dense_vectors_in_order() -> None:
    t = RecordingTransport(dim=4)
    vecs = _plugin(t).embed(["a", "b"])
    assert len(vecs) == 2
    assert all(len(v) == 4 for v in vecs)
    assert vecs[0] == [0.0, 0.0, 0.0, 0.0]
    assert vecs[1] == [1.0, 1.0, 1.0, 1.0]


def test_request_body_carries_model_and_inputs() -> None:
    t = RecordingTransport()
    _plugin(t).embed(["a", "b"])
    assert t.last_body == {"model": "bge-m3", "input": ["a", "b"]}
    url = t.calls[-1][0]
    assert urlparse(url).path == "/v1/embeddings"


def test_embed_query_returns_one_vector() -> None:
    t = RecordingTransport(dim=3)
    vec = _plugin(t).embed_query("x")
    assert vec == [0.0, 0.0, 0.0]
    assert t.last_body == {"model": "bge-m3", "input": ["x"]}


def _real_endpoint_reachable(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        socket.create_connection((host, port), timeout=2).close()
        return True
    except OSError:
        return False


@pytest.mark.integration
def test_real_embeddings_endpoint() -> None:
    base_url = os.environ.get("CITENEXUS_EMBED_BASE_URL", "http://localhost:11434/v1")
    if not _real_endpoint_reachable(base_url):
        pytest.skip(f"embedding endpoint unreachable: {base_url}")
    plugin = OpenAICompatibleEmbedding(
        base_url=base_url,
        model=os.environ.get("CITENEXUS_EMBED_MODEL", "bge-m3"),
    )
    vecs = plugin.embed(["hello", "world"])
    assert len(vecs) == 2
    assert len(vecs[0]) > 0
    assert all(isinstance(x, float) for x in vecs[0])
