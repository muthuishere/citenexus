"""LLM wiki distillation — cross-referenced pages from a small model (§10b).

A small injected model (temperature 0) compiles the corpus EUs into concept
pages + per-document summaries with [[links]]. Enhancement-only: any failure
returns None and the store falls back to its deterministic pages. eu_refs the
model invents are dropped — navigate-not-cite needs every ref to resolve.
"""

from __future__ import annotations

import json

from trustrag.wiki.distill import LLMWikiDistiller

_CORPUS = {
    "nda": (("nda::0", "The employee shall not disclose confidential information."),),
    "policy": (("policy::0", "Confidential material stays on approved devices."),),
}

_REPLY = {
    "pages": [
        {
            "page_id": "confidentiality",
            "title": "Confidentiality",
            "summary": "Both documents restrict confidential information.",
            "keywords": ["confidential", "disclosure"],
            "links": ["doc-nda", "doc-policy"],
            "eu_refs": ["nda::0", "policy::0", "made-up::9"],
        },
        {
            "page_id": "doc-nda",
            "title": "NDA",
            "summary": "Non-disclosure agreement.",
            "keywords": ["nda"],
            "links": ["confidentiality"],
            "eu_refs": ["nda::0"],
        },
    ]
}


class RecordingTransport:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.calls.append((url, body, dict(headers)))
        payload = {"choices": [{"message": {"content": self.content}}]}
        return json.dumps(payload).encode("utf-8")

    @property
    def last_body(self) -> dict[str, object]:
        body: dict[str, object] = json.loads(self.calls[-1][1])
        return body


def _distiller(t: RecordingTransport) -> LLMWikiDistiller:
    return LLMWikiDistiller(
        base_url="http://small.test/v1", model="gemini-2.5-flash-lite", transport=t
    )


def test_distill_returns_cross_referenced_pages() -> None:
    t = RecordingTransport(json.dumps(_REPLY))
    pages = _distiller(t).distill(_CORPUS)
    assert pages is not None
    concept = pages[0]
    assert concept.page_id == "confidentiality"
    assert concept.links == ("doc-nda", "doc-policy")
    # Concept pages span documents: EUs from both docs, hallucinated refs dropped.
    assert concept.eu_refs == ("nda::0", "policy::0")


def test_distill_prompt_carries_corpus_and_temperature_zero() -> None:
    t = RecordingTransport(json.dumps(_REPLY))
    _distiller(t).distill(_CORPUS)
    body = t.last_body
    assert body["temperature"] == 0.0
    blob = json.dumps(body["messages"])
    assert "nda::0" in blob
    assert "Confidential material stays on approved devices." in blob


def test_distill_prose_wrapped_json_still_parses() -> None:
    t = RecordingTransport("Here is your wiki:\n" + json.dumps(_REPLY) + "\nEnjoy!")
    pages = _distiller(t).distill(_CORPUS)
    assert pages is not None
    assert {page.page_id for page in pages} == {"confidentiality", "doc-nda"}


def test_distill_failure_degrades_to_none() -> None:
    def boom(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        raise RuntimeError("endpoint down")

    distiller = LLMWikiDistiller(base_url="http://x/v1", model="m", transport=boom)
    assert distiller.distill(_CORPUS) is None


def test_distill_garbage_reply_degrades_to_none() -> None:
    assert _distiller(RecordingTransport("not json at all")).distill(_CORPUS) is None
    assert _distiller(RecordingTransport('{"pages": "nope"}')).distill(_CORPUS) is None
    assert _distiller(RecordingTransport('{"pages": []}')).distill(_CORPUS) is None


def test_distill_empty_corpus_is_none_without_a_call() -> None:
    t = RecordingTransport(json.dumps(_REPLY))
    assert _distiller(t).distill({}) is None
    assert t.calls == []
