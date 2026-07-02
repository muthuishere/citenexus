"""``OpenAICompatibleGenerator`` — the answering LLM behind ``ask()`` (§4b).

TrustRAG bundles no models: the answering model is an injected, OpenAI-compatible
chat endpoint (local Ollama ``qwen2.5``, OpenRouter, vLLM, …). This plugin posts
``{model, messages, temperature, ...}`` to ``{base_url}/chat/completions`` and
reads ``choices[0].message.content``.

Two invariants make it the strict-mode answering seam:

- **Temperature is always sent** — default ``0.0`` (spec §4b "temp-0 grounded").
  A grounded RAG answer must be deterministic; the temperature travels on every
  request, never left to the endpoint's default.
- **Grounding is instructed, then verified.** The prompt tells the model to
  answer *only* from the passage and in the required language, but the ``AnswerFlow``
  faithfulness gate — not the prompt — is what actually enforces the guarantee.

The HTTP call is injected via a ``transport`` callable so unit tests stay
hermetic; the default transport is a stdlib ``urllib.request`` wrapper (no new
dependency), matching the embedding/rerank clients.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable

from trustrag.telemetry.events import TokenUsage

# (url, json body, headers) -> response bytes. The single seam that lets unit
# tests run hermetically while the default wires stdlib urllib.
Transport = Callable[[str, bytes, dict[str, str]], bytes]

_SYSTEM_PROMPT = (
    "You are a strict, evidence-first assistant. Answer the question by quoting "
    "the exact sentence or phrase from the provided passage that answers it — "
    "VERBATIM, word for word, with no rephrasing, no added words, and no "
    "commentary. If the passage does not contain the answer, say you cannot "
    "answer from the evidence. The verifier rejects any word not present in the "
    "passage, so never paraphrase. Quote in the passage's own language when it "
    "matches the requested ISO code; otherwise still prefer the passage's exact "
    "wording."
)


def _urllib_transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    """The default transport: a stdlib ``urllib.request`` POST (no new deps).

    Sends an explicit ``User-Agent`` — some hosted endpoints (e.g. behind
    Cloudflare) reject the default ``Python-urllib`` agent with a 403.
    """
    request = urllib.request.Request(
        url, data=body, headers={"User-Agent": "trustrag", **headers}, method="POST"
    )
    with urllib.request.urlopen(request) as response:
        data: bytes = response.read()
    return data


class OpenAICompatibleGenerator:
    """Grounded answers over an OpenAI-compatible ``/chat/completions`` endpoint.

    Implements the ``answer/flow.Generator`` protocol so it drops straight into
    ``AnswerFlow`` / ``TrustRAG(generator=...)``.
    """

    plugin_version = "openai-generator-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_env: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        transport: Transport | None = None,
    ) -> None:
        # Store only the env-var *name*, never the secret value.
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key_env = api_key_env
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._transport: Transport = transport or _urllib_transport
        # Token usage from the most recent call, for telemetry. ``None`` until
        # the first ``answer()``; the client reads it to emit a generate event.
        self.last_usage: TokenUsage | None = None

    @property
    def _endpoint(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key_env:
            # Read the key at call time; carry it ONLY in the Authorization
            # header. The value never lands on ``self`` and is never logged.
            key = os.environ.get(self._api_key_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        """Generate a grounded answer from ``passage`` in ``answer_language``."""
        user = (
            f"Answer language (ISO code): {answer_language}\n\n"
            f"Passage:\n{passage}\n\n"
            f"Question: {question}"
        )
        request: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            # Always sent — a grounded answer must be deterministic (§4b).
            "temperature": self._temperature,
        }
        if self._max_tokens is not None:
            request["max_tokens"] = self._max_tokens
        body = json.dumps(request).encode("utf-8")
        raw = self._transport(self._endpoint, body, self._headers())
        payload = json.loads(raw)
        self.last_usage = _usage_of(payload)
        content: str = payload["choices"][0]["message"]["content"]
        return content


def _usage_of(payload: dict[str, object]) -> TokenUsage | None:
    """Parse the OpenAI ``usage`` block into a ``TokenUsage`` (None if absent)."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    return TokenUsage(
        input=int(usage.get("prompt_tokens", 0)),
        output=int(usage.get("completion_tokens", 0)),
    )
