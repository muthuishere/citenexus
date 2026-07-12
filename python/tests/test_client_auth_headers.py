"""First-class auth on the direct model clients — toolnexus ``${ENV}`` style.

You pass ``headers={"Authorization": "Bearer ${API_KEY}"}`` straight to a model
client; the client holds only the TEMPLATE and forwards it to the transport,
which expands ``${ENV}`` from the environment at the request boundary. The
secret's value never lives on the client object — so it can't leak into a repr,
a config dump, or the context window.
"""

from __future__ import annotations

import json

import pytest

from citenexus.answer.generator import OpenAICompatibleGenerator
from citenexus.embed.client import OpenAICompatibleEmbedding
from citenexus.http import HttpClient
from citenexus.retrieve.rerank import OpenAICompatibleReranker
from citenexus.vision.client import OpenAICompatibleVision

_TEMPLATE = {"Authorization": "Bearer ${CN_MODEL_KEY}"}


def _build_all() -> list[object]:
    return [
        OpenAICompatibleEmbedding(base_url="http://x/v1", model="m", headers=_TEMPLATE),
        OpenAICompatibleGenerator(base_url="http://x/v1", model="m", headers=_TEMPLATE),
        OpenAICompatibleReranker(base_url="http://x/v1", model="m", headers=_TEMPLATE),
        OpenAICompatibleVision(base_url="http://x/v1", model="m", headers=_TEMPLATE),
    ]


@pytest.mark.parametrize("client", _build_all())
def test_client_holds_only_the_header_template(client: object) -> None:
    headers = client._headers()  # type: ignore[attr-defined]
    assert headers["Content-Type"] == "application/json"
    # The TEMPLATE is stored — never a resolved secret value.
    assert headers["Authorization"] == "Bearer ${CN_MODEL_KEY}"
    # The literal value never appears anywhere on the object's repr/state.
    assert "sk-" not in repr(vars(client))


def test_embedding_forwards_template_and_transport_expands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CN_MODEL_KEY", "sk-live-999")
    seen: dict[str, str] = {}

    def recorder(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        seen.update(headers)
        return json.dumps({"data": [{"embedding": [0.1, 0.2]}]}).encode("utf-8")

    client = OpenAICompatibleEmbedding(
        base_url="http://x/v1", model="m", transport=recorder, headers=_TEMPLATE
    )
    client.embed(["hello"])

    # The client forwards the TEMPLATE untouched — expansion is the transport's job.
    assert seen["Authorization"] == "Bearer ${CN_MODEL_KEY}"
    # And a real HttpClient resolves that same template to the live value at the edge.
    assert HttpClient().resolve_headers(seen)["Authorization"] == "Bearer sk-live-999"
