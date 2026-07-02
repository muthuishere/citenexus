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
