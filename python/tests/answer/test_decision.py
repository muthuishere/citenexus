"""Structured single-decision output — parsed off the completion path, NOT tools.

The deep-ask loop asks the model one small decision per hop (sufficient? next
query?) as a JSON object on the EXISTING completion path — no OpenAI/Anthropic
function-calling. These prove the parse + the ``Completion`` seam offline.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from citenexus.answer.anthropic import AnthropicGenerator
from citenexus.answer.decision import (
    CompletionDecisionModel,
    LoopDecision,
    parse_decision,
)
from citenexus.answer.generator import OpenAICompatibleGenerator
from citenexus.testing.fakes import FakeCompletion, FakeToolLLM


def test_parse_clean_json() -> None:
    d = parse_decision('{"sufficient": true, "next_query": "disclosure penalty"}')
    assert d.sufficient is True
    assert d.next_query == "disclosure penalty"


def test_parse_tolerates_surrounding_prose() -> None:
    raw = 'Sure! Here is my decision:\n{"sufficient": false, "next_query": "more"}\nThanks.'
    d = parse_decision(raw)
    assert d.sufficient is False
    assert d.next_query == "more"


def test_parse_null_next_query_is_none() -> None:
    d = parse_decision('{"sufficient": true, "next_query": null}')
    assert d.next_query is None


def test_parse_unparseable_is_conservative() -> None:
    d = parse_decision("no json here at all")
    assert d == LoopDecision(sufficient=False, next_query=None)


def test_completion_decision_model_parses_off_completion() -> None:
    completion = FakeCompletion(['{"sufficient": false, "next_query": "next hop"}'])
    model = CompletionDecisionModel(completion)
    d = model.decide("q", ["some evidence"])
    assert d.sufficient is False
    assert d.next_query == "next hop"


def test_fake_tool_llm_replays_canned_decisions() -> None:
    fake = FakeToolLLM(
        [LoopDecision(sufficient=False, next_query="a"), LoopDecision(sufficient=True)]
    )
    assert fake.decide("q", []).next_query == "a"
    assert fake.decide("q", []).sufficient is True
    # Drained queue repeats the last decision deterministically.
    assert fake.decide("q", []).sufficient is True


class _RecordingTransport:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.calls.append((url, body, dict(headers)))
        payload = {"choices": [{"message": {"content": self.content}}]}
        return json.dumps(payload).encode("utf-8")


def test_openai_complete_uses_plain_completion_no_tools() -> None:
    t = _RecordingTransport('{"sufficient": true, "next_query": null}')
    gen = OpenAICompatibleGenerator(base_url="http://llm.test/v1", model="qwen2.5", transport=t)
    raw = gen.complete("decide please")
    assert parse_decision(raw).sufficient is True
    url, body, _ = t.calls[-1]
    assert urlparse(url).path == "/v1/chat/completions"
    sent = json.loads(body)
    # A plain completion — one user message, no provider tool/function machinery.
    assert "tools" not in sent
    assert "functions" not in sent
    assert sent["messages"] == [{"role": "user", "content": "decide please"}]


class _RecordingAnthropicTransport:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.calls.append((url, body, dict(headers)))
        payload = {"content": [{"type": "text", "text": self.content}]}
        return json.dumps(payload).encode("utf-8")


def test_anthropic_complete_uses_plain_completion_no_tools() -> None:
    t = _RecordingAnthropicTransport('{"sufficient": false, "next_query": "x"}')
    gen = AnthropicGenerator(base_url="http://ant.test", model="claude", transport=t)
    d = parse_decision(gen.complete("decide please"))
    assert d.next_query == "x"
    _, body, _ = t.calls[-1]
    sent = json.loads(body)
    assert "tools" not in sent
    assert sent["messages"] == [{"role": "user", "content": "decide please"}]
