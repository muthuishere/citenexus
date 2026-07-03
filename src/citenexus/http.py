"""The shared HTTP layer behind every model API (§4b).

Every model client (generator, Anthropic, embedding, rerank, vision, and the
four small-model seams) speaks HTTP through the same ``Transport`` seam:
``(url, json body, headers) -> response bytes``. This module provides the ONE
default implementation — previously five private copies of a urllib wrapper,
none of which honored a timeout.

``HttpClient`` adds what providers actually differ on:

- **Default headers** merged under the per-call ones (gateway headers like
  ``HTTP-Referer``/``X-Title`` for OpenRouter, ``api-version`` for Azure, …).
  Per-call headers — which carry the client's auth — always win, so an extra
  header can never clobber ``Authorization``/``x-api-key``.
- **A real timeout** (default 60s; ``llm.timeout_s`` wires it from config) —
  a hung endpoint no longer hangs ingest forever.
- The ``User-Agent: citenexus`` some Cloudflare-fronted APIs require.

Any callable with the same signature still drops in (hermetic tests inject
recorders), and a custom ``HttpClient(headers=..., timeout_s=...)`` can be
passed wherever a ``transport=`` is accepted.
"""

from __future__ import annotations

import urllib.request
from collections.abc import Callable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr

# (url, json body, headers) -> response bytes. The single seam that lets unit
# tests run hermetically while this module wires real HTTP.
Transport = Callable[[str, bytes, dict[str, str]], bytes]

_USER_AGENT = "citenexus"
_DEFAULT_TIMEOUT_S = 60.0


class HttpClient:
    """The default ``Transport``: stdlib urllib + headers + timeout."""

    def __init__(
        self,
        *,
        headers: Mapping[str, str] | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._headers = dict(headers or {})
        self.timeout_s = timeout_s

    def build_headers(self, call_headers: Mapping[str, str]) -> dict[str, str]:
        """Merge order: User-Agent < client defaults < per-call (auth wins)."""
        return {"User-Agent": _USER_AGENT, **self._headers, **call_headers}

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        request = urllib.request.Request(
            url, data=body, headers=self.build_headers(headers), method="POST"
        )
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            data: bytes = response.read()
        return data


#: Shared default instance — what every model client uses when no transport is
#: injected. Stateless, so sharing is safe.
DEFAULT_TRANSPORT = HttpClient()


# --------------------------------------------------------------------------- #
# Typed provider endpoints — config data + a styled client, declared ONCE.
# --------------------------------------------------------------------------- #

# Pre-hook: (url, body, headers) -> optionally a modified (url, body, headers).
RequestHook = Callable[[str, bytes, dict[str, str]], "tuple[str, bytes, dict[str, str]] | None"]
# Post-hook: (url, response bytes) -> optionally replaced response bytes.
ResponseHook = Callable[[str, bytes], "bytes | None"]


class HttpEndpoint(BaseModel):
    """A provider connection declared ONCE: url + headers + key + hooks.

    THE LIBRARY READS NO ENVIRONMENT: the application resolves its own secrets
    and passes the key VALUE here — held as a pydantic ``SecretStr``, so an
    endpoint is still safe to repr/log. Reusable across config sections (one
    ``gemini`` object can serve ``llm``, ``reformulation``, ``context_model``…).

        import os
        from citenexus import GeminiHttpEndpoint, OpenAIHttpEndpoint

        gemini = GeminiHttpEndpoint(api_key=os.environ["GEMINI_API_KEY"])
        jina = OpenAIHttpEndpoint(base_url="https://api.jina.ai/v1",
                                  api_key=os.environ["JINA_API_KEY"])

    ``pre``/``post`` hooks run around every request (signing, tracing,
    logging); a pre-hook may rewrite (url, body, headers), a post-hook may
    replace the response bytes. ``auth_header``/``auth_scheme`` cover
    non-Bearer providers (Azure: ``auth_header="api-key", auth_scheme=None``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    base_url: str
    api_key: SecretStr | None = None
    headers: dict[str, str] = {}
    timeout_s: float = _DEFAULT_TIMEOUT_S
    auth_header: str = "Authorization"
    auth_scheme: str | None = "Bearer"
    pre: RequestHook | None = None
    post: ResponseHook | None = None

    #: The wire protocol this endpoint speaks; subclasses override.
    protocol: Literal["openai", "anthropic"] = "openai"

    def build_transport(self, inner: Transport | None = None) -> Transport:
        """The styled transport: hooks + headers + auth around ``inner``."""
        base: Transport = inner or HttpClient(headers=self.headers, timeout_s=self.timeout_s)
        endpoint = self

        def call(url: str, body: bytes, headers: dict[str, str]) -> bytes:
            merged = {**endpoint.headers, **headers} if inner is not None else dict(headers)
            if endpoint.api_key is not None:
                merged.pop("Authorization", None)
                key = endpoint.api_key.get_secret_value()
                merged[endpoint.auth_header] = (
                    f"{endpoint.auth_scheme} {key}" if endpoint.auth_scheme else key
                )
            if endpoint.pre is not None:
                rewritten = endpoint.pre(url, body, merged)
                if rewritten is not None:
                    url, body, merged = rewritten
            response = base(url, body, merged)
            if endpoint.post is not None:
                replaced = endpoint.post(url, response)
                if replaced is not None:
                    response = replaced
            return response

        return call


class OpenAIHttpEndpoint(HttpEndpoint):
    """Any OpenAI-compatible ``/chat/completions``-style API (OpenAI, Jina,
    vLLM, gateways). Default base_url is OpenAI's; override freely."""

    base_url: str = "https://api.openai.com/v1"


class GeminiHttpEndpoint(HttpEndpoint):
    """Gemini's OpenAI-compatible endpoint."""

    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"


class AnthropicHttpEndpoint(HttpEndpoint):
    """Anthropic's native Messages API — x-api-key auth, anthropic wire protocol."""

    base_url: str = "https://api.anthropic.com"
    auth_header: str = "x-api-key"
    auth_scheme: str | None = None
    protocol: Literal["openai", "anthropic"] = "anthropic"


class OpenRouterHttpEndpoint(HttpEndpoint):
    """OpenRouter — add ``headers={"HTTP-Referer": ..., "X-Title": ...}``."""

    base_url: str = "https://openrouter.ai/api/v1"


class OllamaHttpEndpoint(HttpEndpoint):
    """Local Ollama (no key)."""

    base_url: str = "http://localhost:11434/v1"
