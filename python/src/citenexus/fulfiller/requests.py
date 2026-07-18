"""Emit phase — the core's pure builders for the four typed model requests.

The deterministic heart of the emit phase, factored out of any I/O so the exact
request bytes — the URL, the provider-shaped body, the ``${ENV}`` auth reference —
are computed in one place. Each builder shapes an OpenAI-compatible request; auth
is carried by ``${ENV}`` header NAME only, so an emitted request is credential-free
by construction. The bodies are intentionally minimal — the protocol pins *where*
the call happens, not each provider's full wire, which is per-seam migration work.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from citenexus.domain.model import (
    EmbedRequest,
    GenerateRequest,
    JsonObject,
    ModelAuth,
    RerankRequest,
    VisionRequest,
)


def _auth(auth_headers: Mapping[str, str] | None, sign: str | None) -> ModelAuth:
    return ModelAuth(headers=dict(auth_headers or {}), sign=sign)


def build_embed_request(
    *,
    request_id: str,
    base_url: str,
    model: str,
    inputs: Sequence[str],
    auth_headers: Mapping[str, str] | None = None,
    sign: str | None = None,
) -> EmbedRequest:
    """An OpenAI-compatible ``/embeddings`` call over a batch of texts."""
    body: JsonObject = {"model": model, "input": list(inputs)}
    return EmbedRequest(
        request_id=request_id,
        url=f"{base_url}/embeddings",
        body=body,
        auth=_auth(auth_headers, sign),
    )


def build_generate_request(
    *,
    request_id: str,
    base_url: str,
    model: str,
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    auth_headers: Mapping[str, str] | None = None,
    sign: str | None = None,
) -> GenerateRequest:
    """An OpenAI-compatible ``/chat/completions`` call for one user prompt."""
    body: JsonObject = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return GenerateRequest(
        request_id=request_id,
        url=f"{base_url}/chat/completions",
        body=body,
        auth=_auth(auth_headers, sign),
    )


def build_rerank_request(
    *,
    request_id: str,
    base_url: str,
    model: str,
    query: str,
    documents: Sequence[str],
    auth_headers: Mapping[str, str] | None = None,
    sign: str | None = None,
) -> RerankRequest:
    """A cross-encoder ``/rerank`` call over ``query`` and candidate documents."""
    body: JsonObject = {"model": model, "query": query, "documents": list(documents)}
    return RerankRequest(
        request_id=request_id,
        url=f"{base_url}/rerank",
        body=body,
        auth=_auth(auth_headers, sign),
    )


def build_vision_request(
    *,
    request_id: str,
    base_url: str,
    model: str,
    image_url: str,
    prompt: str,
    auth_headers: Mapping[str, str] | None = None,
    sign: str | None = None,
) -> VisionRequest:
    """A ``/chat/completions`` vision call — a prompt plus an ``image_url`` part."""
    body: JsonObject = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
    }
    return VisionRequest(
        request_id=request_id,
        url=f"{base_url}/chat/completions",
        body=body,
        auth=_auth(auth_headers, sign),
    )
