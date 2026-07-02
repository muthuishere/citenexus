"""The shared HttpClient — one HTTP layer for every model API (§4b).

Providers differ in headers (Bearer vs x-api-key vs api-key, gateway headers
like HTTP-Referer), and in patience. HttpClient is the single default transport
behind every model client: default headers, per-client extra headers, a real
timeout, and the User-Agent — merged predictably (base < extras < per-call, so
auth set by the client always wins).
"""

from __future__ import annotations

from citenexus.http import HttpClient


def test_header_merge_order() -> None:
    client = HttpClient(headers={"HTTP-Referer": "https://citenexus.dev", "X-Title": "app"})
    merged = client.build_headers({"Authorization": "Bearer x", "Content-Type": "application/json"})
    assert merged["User-Agent"] == "citenexus"
    assert merged["HTTP-Referer"] == "https://citenexus.dev"
    assert merged["Authorization"] == "Bearer x"  # per-call (auth) wins


def test_per_call_headers_override_defaults() -> None:
    client = HttpClient(headers={"X-Env": "default"})
    assert client.build_headers({"X-Env": "call"})["X-Env"] == "call"


def test_timeout_is_carried() -> None:
    assert HttpClient(timeout_s=7.5).timeout_s == 7.5
    assert HttpClient().timeout_s == 60.0
