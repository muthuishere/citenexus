"""``AnthropicGenerator`` — the answering LLM over Anthropic's Messages API (§4b).

Anthropic is not OpenAI-shaped, so it gets its own client (rather than pretending
a base-url swap is enough): POST ``{base_url}/v1/messages``, auth via the
``x-api-key`` header (not ``Authorization: Bearer``), a required
``anthropic-version`` header, ``system`` as a top-level field, a REQUIRED
``max_tokens``, and a ``content[0].text`` response.

It implements the same ``answer/flow.Generator`` protocol as
``OpenAICompatibleGenerator``, so it drops into ``AnswerFlow`` / ``CiteNexus``
unchanged. Like the other clients: temperature is always sent (default 0.0 —
grounded answers are deterministic), the key flows only through a header and never
lands on ``self``, and the HTTP call goes through an injected ``transport``.
"""

from __future__ import annotations

import json

from citenexus.answer.generator import _SYSTEM_PROMPT
from citenexus.http import DEFAULT_TRANSPORT, Transport
from citenexus.telemetry.events import TokenUsage

# Pinned Messages API version. Bump deliberately, not silently.
_ANTHROPIC_VERSION = "2023-06-01"
# Anthropic requires max_tokens; use a sane default when the caller gives none.
_DEFAULT_MAX_TOKENS = 1024


class AnthropicGenerator:
    """Grounded answers over Anthropic's native ``/v1/messages`` endpoint."""

    plugin_version = "anthropic-generator-v1"

    def __init__(
        self,
        *,
        base_url: str = "https://api.anthropic.com",
        model: str,
        temperature: float = 0.0,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._transport: Transport = transport or DEFAULT_TRANSPORT
        self.last_usage: TokenUsage | None = None

    @property
    def _endpoint(self) -> str:
        return f"{self._base_url}/v1/messages"

    def _headers(self) -> dict[str, str]:
        # Auth + provider headers are the ENDPOINT layer's job (HttpEndpoint
        # transport); wire clients only speak JSON.
        return {"Content-Type": "application/json"}

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        """Generate a grounded answer from ``passage`` in ``answer_language``."""
        user = (
            f"Answer language (ISO code): {answer_language}\n\n"
            f"Passage:\n{passage}\n\n"
            f"Question: {question}"
        )
        request: dict[str, object] = {
            "model": self._model,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user}],
            # Both always sent — max_tokens is required, temperature keeps answers
            # deterministic (§4b).
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        body = json.dumps(request).encode("utf-8")
        raw = self._transport(self._endpoint, body, self._headers())
        payload = json.loads(raw)
        self.last_usage = _usage_of(payload)
        return _text_of(payload)


def _text_of(payload: dict[str, object]) -> str:
    """Concatenate the text blocks of an Anthropic message response."""
    blocks = payload.get("content", [])
    if not isinstance(blocks, list):
        return ""
    parts = [
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "".join(parts)


def _usage_of(payload: dict[str, object]) -> TokenUsage | None:
    """Parse Anthropic's ``usage`` block into a ``TokenUsage`` (None if absent)."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    return TokenUsage(
        input=int(usage.get("input_tokens", 0)),
        output=int(usage.get("output_tokens", 0)),
    )
