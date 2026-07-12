"""The shared HttpClient — one HTTP layer for every model API (§4b).

Providers differ in headers (Bearer vs x-api-key vs api-key, gateway headers
like HTTP-Referer), and in patience. HttpClient is the single default transport
behind every model client: default headers, per-client extra headers, a real
timeout, and the User-Agent — merged predictably (base < extras < per-call, so
auth set by the client always wins).
"""

from __future__ import annotations

import pytest

from citenexus.http import HttpClient, expand_env


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


def test_env_placeholder_expands_only_at_call_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CN_TEST_KEY", "sk-secret-123")
    client = HttpClient()
    template = {"Authorization": "Bearer ${CN_TEST_KEY}"}

    # build_headers keeps the TEMPLATE — the value is not materialized here...
    assert client.build_headers(template)["Authorization"] == "Bearer ${CN_TEST_KEY}"
    # ...only resolve_headers (used at the request edge) expands it.
    assert client.resolve_headers(template)["Authorization"] == "Bearer sk-secret-123"
    # And the caller's dict is never mutated (no value leaks back).
    assert template["Authorization"] == "Bearer ${CN_TEST_KEY}"


def test_missing_env_placeholder_expands_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CN_ABSENT", raising=False)
    assert expand_env("Bearer ${CN_ABSENT}") == "Bearer "
    assert HttpClient().resolve_headers({"X": "${CN_ABSENT}"})["X"] == ""
