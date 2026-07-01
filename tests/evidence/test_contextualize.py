"""Contextual retrieval — a small model situates each chunk (Anthropic technique).

Prepend a 50-100 token, LLM-generated blurb to each chunk BEFORE embedding/BM25
so a chunk like "revenue grew 3%" carries "this is Acme's Q2 report" and retrieves
correctly. SAFETY INVARIANT for legal/medical: the context enriches the *indexed
text* only — the cited passage stays the VERBATIM chunk, never the model's words.
Uses a small, cheap model (injected, temperature 0), mirroring the other clients.
"""

from __future__ import annotations

import json

from trustrag.evidence.contextualize import Contextualizer


class RecordingTransport:
    def __init__(self, context: str = "This chunk is from Acme's Q2 2026 report.") -> None:
        self.context = context
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.calls.append((url, body, dict(headers)))
        payload = {"choices": [{"message": {"content": self.context}}]}
        return json.dumps(payload).encode("utf-8")

    @property
    def last_body(self) -> dict[str, object]:
        body: dict[str, object] = json.loads(self.calls[-1][1])
        return body


def _ctx(t: RecordingTransport) -> Contextualizer:
    return Contextualizer(
        base_url="http://small.test/v1", model="gemini-2.5-flash-lite", transport=t
    )


def test_context_prefix_prepended_to_chunk() -> None:
    t = RecordingTransport(context="This is from Acme's annual report, revenue section.")
    out = _ctx(t).contextualize(
        chunk="Revenue grew 3% over the prior quarter.",
        document="Acme Corp Annual Report 2026. Revenue section...",
    )
    assert out.startswith("This is from Acme's annual report, revenue section.")
    assert "Revenue grew 3% over the prior quarter." in out


def test_prompt_includes_chunk_and_document() -> None:
    t = RecordingTransport()
    _ctx(t).contextualize(chunk="The clause forbids disclosure.", document="Full NDA text.")
    blob = json.dumps(t.last_body["messages"])
    assert "The clause forbids disclosure." in blob
    assert "Full NDA text." in blob


def test_temperature_zero() -> None:
    t = RecordingTransport()
    _ctx(t).contextualize(chunk="c", document="d")
    assert t.last_body["temperature"] == 0.0


def test_empty_context_falls_back_to_bare_chunk() -> None:
    t = RecordingTransport(context="   ")
    out = _ctx(t).contextualize(chunk="Bare chunk.", document="Doc.")
    assert out == "Bare chunk."


def test_contextualize_never_raises_returns_chunk_on_error() -> None:
    def boom(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        raise RuntimeError("endpoint down")

    ctx = Contextualizer(base_url="http://x/v1", model="m", transport=boom)
    # Degrade gracefully: contextualization is an enhancement, never a hard dep.
    assert ctx.contextualize(chunk="Keep me.", document="Doc.") == "Keep me."
