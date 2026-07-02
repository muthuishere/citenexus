"""LLM graph distillation — real entities + typed relations behind the graph signal.

The deterministic graph is token co-mention. The distiller upgrades it: a SMALL
model reads the corpus EUs and extracts named ENTITIES (each grounded in real
eu_refs) and typed RELATIONS between them. Same contract as the wiki distiller:
enhancement-only (any failure -> None -> deterministic fallback), hallucinated
eu_refs sanitized against the corpus, entities with no surviving grounding
dropped — the graph can route retrieval but never invent evidence.
"""

from __future__ import annotations

import json

from citenexus.graph.distill import GraphDistiller, LLMGraphDistiller

from citenexus.graph.store import GraphIndex


def _reply(payload: dict[str, object]) -> bytes:
    return json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode()


_GOOD = {
    "entities": [
        {"label": "Acme Corp", "eu_refs": ["nda::0::0", "contract::0::0"]},
        {"label": "Confidentiality Clause", "eu_refs": ["nda::0::0"]},
        {"label": "Hallucinated Co", "eu_refs": ["made-up::9"]},  # must be dropped
    ],
    "relations": [
        {
            "source": "Acme Corp",
            "target": "Confidentiality Clause",
            "relation": "bound_by",
            "weight": 2,
        },
        {"source": "Acme Corp", "target": "Hallucinated Co", "relation": "owns", "weight": 1},
    ],
}

_INPUT = {
    "nda": [("nda::0::0", "Acme Corp employees shall not disclose confidential information.")],
    "contract": [("contract::0::0", "Acme Corp termination requires thirty days notice.")],
}


class RecordingTransport:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.calls: list[bytes] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.calls.append(body)
        return self.response


def _distiller(t: RecordingTransport) -> LLMGraphDistiller:
    return LLMGraphDistiller(base_url="http://small.test/v1", model="m", transport=t)


def test_satisfies_protocol() -> None:
    assert isinstance(_distiller(RecordingTransport(b"")), GraphDistiller)


def test_distills_entities_and_typed_relations() -> None:
    t = RecordingTransport(_reply(_GOOD))
    index = _distiller(t).distill(_INPUT)
    assert isinstance(index, GraphIndex)
    labels = {n.label for n in index.nodes}
    assert labels == {"Acme Corp", "Confidentiality Clause"}  # hallucination dropped
    acme = next(n for n in index.nodes if n.label == "Acme Corp")
    assert acme.eu_refs == ("contract::0::0", "nda::0::0")  # sorted, only real EUs
    # only the relation between surviving entities remains, and it is typed
    assert len(index.edges) == 1
    assert index.edges[0].relation == "bound_by"
    assert index.edges[0].weight == 2


def test_prompt_carries_corpus_and_temperature_zero() -> None:
    t = RecordingTransport(_reply(_GOOD))
    _distiller(t).distill(_INPUT)
    body = json.loads(t.calls[0])
    assert body["temperature"] == 0.0
    blob = json.dumps(body["messages"])
    assert "nda::0::0" in blob and "thirty days" in blob


def test_failure_and_garbage_return_none() -> None:
    def boom(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        raise RuntimeError("down")

    assert (
        LLMGraphDistiller(base_url="http://x/v1", model="m", transport=boom).distill(_INPUT) is None
    )
    garbage = RecordingTransport(b'{"choices":[{"message":{"content":"not json"}}]}')
    assert _distiller(garbage).distill(_INPUT) is None
    empty = RecordingTransport(_reply({"entities": [], "relations": []}))
    assert _distiller(empty).distill(_INPUT) is None
    assert _distiller(RecordingTransport(_reply(_GOOD))).distill({}) is None
