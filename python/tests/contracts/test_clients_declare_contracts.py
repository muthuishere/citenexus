"""The four shipped clients are checkable implementations of the contracts.

Before this change, `OpenAICompatibleGenerator` and `OpenAICompatibleVision`
declared *nothing* — the `Generator` Protocol and the `VisionPlugin` ABC both
existed and neither client named them. A contract nobody declares is a comment.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from citenexus import (
    OpenAICompatibleEmbedding,
    OpenAICompatibleGenerator,
    OpenAICompatibleReranker,
    OpenAICompatibleVision,
)
from citenexus.answer.anthropic import AnthropicGenerator
from citenexus.contracts import (
    CompletionProvider,
    EmbeddingProvider,
    GeneratorProvider,
    RerankerProvider,
    SequenceEmbedder,
    VisionProvider,
)
from citenexus.plugins.base import EmbeddingPlugin, RerankerPlugin, VisionPlugin
from citenexus.retrieve.types import Candidate, RetrievalSignal


def _transport(payload: object):  # type: ignore[no-untyped-def]
    def send(url: str, body: bytes, headers: Mapping[str, str]) -> bytes:
        return json.dumps(payload).encode("utf-8")

    return send


EMBED_REPLY = {"data": [{"embedding": [0.1, 0.2]}]}
CHAT_REPLY = {"choices": [{"message": {"content": "hello"}}]}
VISION_REPLY = {"choices": [{"message": {"content": '{"short_caption": "a chart"}'}}]}
RERANK_REPLY = {"results": [{"index": 0, "relevance_score": 1.0}]}
ANTHROPIC_REPLY = {"content": [{"type": "text", "text": "hello"}]}


def _embedding() -> OpenAICompatibleEmbedding:
    return OpenAICompatibleEmbedding(
        base_url="http://x/v1", model="m", transport=_transport(EMBED_REPLY), headers={}
    )


def _generator() -> OpenAICompatibleGenerator:
    return OpenAICompatibleGenerator(
        base_url="http://x/v1", model="m", transport=_transport(CHAT_REPLY), headers={}
    )


def _vision() -> OpenAICompatibleVision:
    return OpenAICompatibleVision(
        base_url="http://x/v1", model="m", transport=_transport(VISION_REPLY), headers={}
    )


def _reranker() -> OpenAICompatibleReranker:
    return OpenAICompatibleReranker(
        base_url="http://x/v1", model="m", transport=_transport(RERANK_REPLY), headers={}
    )


def _anthropic() -> AnthropicGenerator:
    return AnthropicGenerator(base_url="http://x", model="m", transport=_transport(ANTHROPIC_REPLY))


# --- every client declares its contract -------------------------------------


@pytest.mark.parametrize(
    ("build", "contract"),
    [
        (_embedding, EmbeddingProvider),
        (_embedding, SequenceEmbedder),
        (_generator, GeneratorProvider),
        (_generator, CompletionProvider),
        (_anthropic, GeneratorProvider),
        (_anthropic, CompletionProvider),
        (_vision, VisionProvider),
        (_reranker, RerankerProvider),
    ],
)
def test_client_satisfies_its_contract(build, contract: type) -> None:  # type: ignore[no-untyped-def]
    assert isinstance(build(), contract)


@pytest.mark.parametrize(
    ("build", "contract"),
    [
        (_embedding, EmbeddingProvider),
        (_generator, GeneratorProvider),
        (_generator, CompletionProvider),
        (_vision, VisionProvider),
        (_reranker, RerankerProvider),
    ],
)
def test_client_declares_the_contract_nominally(build, contract: type) -> None:  # type: ignore[no-untyped-def]
    """Declared, not merely accidental — so mypy checks it on every run."""
    assert contract in type(build()).__mro__


# --- the pre-existing ABCs keep working (0.x: deprecated-not-removed) -------


def test_embedding_client_is_still_an_embedding_plugin() -> None:
    assert isinstance(_embedding(), EmbeddingPlugin)


def test_reranker_client_is_still_a_reranker_plugin() -> None:
    assert isinstance(_reranker(), RerankerPlugin)


def test_vision_client_now_declares_the_vision_plugin_abc_it_never_used() -> None:
    assert isinstance(_vision(), VisionPlugin)


# --- the uniform constructor is unchanged -----------------------------------


@pytest.mark.parametrize("build", [_embedding, _generator, _vision, _reranker])
def test_uniform_keyword_only_constructor(build) -> None:  # type: ignore[no-untyped-def]
    client = build()
    assert client.plugin_version


def test_constructors_are_keyword_only() -> None:
    with pytest.raises(TypeError):
        OpenAICompatibleEmbedding("http://x/v1", "m")  # type: ignore[misc]
    with pytest.raises(TypeError):
        OpenAICompatibleGenerator("http://x/v1", "m")  # type: ignore[misc]
    with pytest.raises(TypeError):
        OpenAICompatibleVision("http://x/v1", "m")  # type: ignore[misc]
    with pytest.raises(TypeError):
        OpenAICompatibleReranker("http://x/v1", "m")  # type: ignore[misc]


# --- the contract methods actually work -------------------------------------


def test_embedding_embed_many_returns_one_vector_per_text() -> None:
    calls: list[bytes] = []

    def send(url: str, body: bytes, headers: Mapping[str, str]) -> bytes:
        calls.append(body)
        payload = json.loads(body)
        return json.dumps(
            {"data": [{"embedding": [float(len(t))]} for t in payload["input"]]}
        ).encode()

    client = OpenAICompatibleEmbedding(base_url="http://x/v1", model="m", transport=send)
    assert client.embed_many(["a", "bb", "ccc"]) == [[1.0], [2.0], [3.0]]
    assert len(calls) == 1


def test_embedding_embed_many_batches_by_batch_size() -> None:
    sizes: list[int] = []

    def send(url: str, body: bytes, headers: Mapping[str, str]) -> bytes:
        texts = json.loads(body)["input"]
        sizes.append(len(texts))
        return json.dumps({"data": [{"embedding": [1.0]} for _ in texts]}).encode()

    client = OpenAICompatibleEmbedding(
        base_url="http://x/v1", model="m", transport=send, batch_size=2
    )
    assert len(client.embed_many(["a", "b", "c", "d", "e"])) == 5
    assert sizes == [2, 2, 1]


def test_embedding_embed_many_preserves_order_across_batches() -> None:
    def send(url: str, body: bytes, headers: Mapping[str, str]) -> bytes:
        texts = json.loads(body)["input"]
        return json.dumps({"data": [{"embedding": [float(len(t))]} for t in texts]}).encode()

    client = OpenAICompatibleEmbedding(
        base_url="http://x/v1", model="m", transport=send, batch_size=2
    )
    texts = ["x" * i for i in range(1, 8)]
    assert client.embed_many(texts) == [[float(i)] for i in range(1, 8)]


def test_embedding_embed_many_on_empty_input_makes_no_request() -> None:
    def send(url: str, body: bytes, headers: Mapping[str, str]) -> bytes:
        raise AssertionError("no request for an empty batch")

    client = OpenAICompatibleEmbedding(base_url="http://x/v1", model="m", transport=send)
    assert client.embed_many([]) == []


def test_generator_answer_and_complete() -> None:
    gen = _generator()
    assert gen.answer("q", "p") == "hello"
    assert gen.complete("prompt") == "hello"


def test_vision_describe_returns_a_mapping() -> None:
    out = _vision().describe(b"\x89PNG")
    assert out["short_caption"] == "a chart"


def test_reranker_rerank_returns_candidates() -> None:
    cand = Candidate(eu_id="e1", score=1.0, signal=RetrievalSignal.vector, text="t")
    assert _reranker().rerank("q", [cand]) == [cand]
