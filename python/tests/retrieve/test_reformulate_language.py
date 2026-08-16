"""The reformulator's target language + the (query, language) cache (ADR-0013).

The reformulator was hardwired to English, which fixes "French question, English
corpus" and does nothing for "English question, Tamil corpus" — where the token
sets are disjoint and measured lexical recall is 0/6. The target is now a
parameter defaulting to "en", and the default must be byte-identical to what
shipped, because `conformance/prompts.json` pins the English prompt as a
cross-port contract.
"""

from __future__ import annotations

import json

from citenexus.retrieve.reformulate import _PROMPT, _PROMPT_TEMPLATE, QueryReformulator


class RecordingTransport:
    """Returns a canned reply per target language; records every request."""

    def __init__(self, replies: dict[str, str] | None = None, *, fail: bool = False) -> None:
        self._replies = replies or {}
        self.prompts: list[str] = []
        self.fail = fail

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        payload = json.loads(body)
        prompt = payload["messages"][0]["content"]
        self.prompts.append(prompt)
        if self.fail:
            raise ConnectionError("reformulation endpoint is down")
        reply = next((v for k, v in self._replies.items() if k in prompt), "rewritten")
        return json.dumps({"choices": [{"message": {"content": reply}}]}).encode("utf-8")

    @property
    def calls(self) -> int:
        return len(self.prompts)


def _reformulator(t: RecordingTransport) -> QueryReformulator:
    return QueryReformulator(base_url="http://small.test/v1", model="small", transport=t)


_Q = "Can the employee disclose confidential information?"


# --------------------------------------------------------------------------- #
# The default is unchanged, byte-for-byte
# --------------------------------------------------------------------------- #


def test_default_language_prompt_is_byte_identical_to_the_pinned_english_prompt() -> None:
    t = RecordingTransport()
    _reformulator(t).reformulate(_Q)
    assert t.prompts[0] == _PROMPT.format(query=_Q)


def test_the_pinned_prompt_constant_still_says_english() -> None:
    # conformance/prompts.json pins this string. Generalising the target may not
    # move it; the template is what the runtime formats.
    assert "in English for retrieving documents" in _PROMPT
    assert "{language}" not in _PROMPT
    assert "{language}" in _PROMPT_TEMPLATE


def test_explicit_en_is_the_same_prompt_as_the_default() -> None:
    a, b = RecordingTransport(), RecordingTransport()
    _reformulator(a).reformulate(_Q)
    _reformulator(b).reformulate(_Q, "en")
    assert a.prompts == b.prompts


# --------------------------------------------------------------------------- #
# Other targets
# --------------------------------------------------------------------------- #


def test_target_language_is_named_in_the_prompt() -> None:
    t = RecordingTransport()
    _reformulator(t).reformulate(_Q, "ta")
    assert "in Tamil for retrieving documents" in t.prompts[0]


def test_identifier_preservation_instruction_survives_every_target() -> None:
    t = RecordingTransport()
    r = _reformulator(t)
    for code in ("en", "ta", "hi", "ja"):
        r.reformulate(_Q, code)
    for prompt in t.prompts:
        assert "Keep names, numbers, and technical identifiers exactly as written." in prompt


def test_an_unknown_code_passes_through_rather_than_exploding() -> None:
    # The capability refusal is lang/search.py's job and it runs first; a
    # reformulator handed an odd code directly should still do something sane.
    t = RecordingTransport()
    _reformulator(t).reformulate(_Q, "zz")
    assert "in zz for retrieving documents" in t.prompts[0]


# --------------------------------------------------------------------------- #
# The cache is keyed by the PAIR
# --------------------------------------------------------------------------- #


def test_one_model_call_per_query_and_language() -> None:
    t = RecordingTransport()
    r = _reformulator(t)
    for _ in range(3):
        r.reformulate(_Q, "ta")
    assert t.calls == 1


def test_distinct_languages_are_cached_separately() -> None:
    t = RecordingTransport()
    r = _reformulator(t)
    r.reformulate(_Q, "ta")
    r.reformulate(_Q, "hi")
    r.reformulate(_Q, "ta")
    r.reformulate(_Q, "hi")
    assert t.calls == 2


def test_distinct_queries_are_cached_separately() -> None:
    t = RecordingTransport()
    r = _reformulator(t)
    r.reformulate("one", "ta")
    r.reformulate("two", "ta")
    r.reformulate("one", "ta")
    assert t.calls == 2


def test_a_failure_is_cached_under_the_same_pair() -> None:
    t = RecordingTransport(fail=True)
    r = _reformulator(t)
    assert [r.reformulate(_Q, "ta") for _ in range(5)] == [None] * 5
    assert t.calls == 1, "a dead endpoint must not be hammered once per call site"


def test_a_failure_for_one_language_does_not_poison_another() -> None:
    t = RecordingTransport(fail=True)
    r = _reformulator(t)
    r.reformulate(_Q, "ta")
    r.reformulate(_Q, "hi")
    assert t.calls == 2


def test_a_reformulation_equal_to_the_original_adds_nothing() -> None:
    t = RecordingTransport({"Query:": _Q})
    assert _reformulator(t).reformulate(_Q, "ta") is None


def test_an_empty_reply_adds_nothing() -> None:
    t = RecordingTransport({"Query:": "   "})
    assert _reformulator(t).reformulate(_Q, "ta") is None
