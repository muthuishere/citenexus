"""The two-phase model-fulfiller protocol — typed requests (spec: model-fulfiller).

Generalizes the vision emit/fulfill seam (``domain.vision``) to every remote-model
call. The core builds and **emits** a typed ``ModelRequest`` — ``EmbedRequest`` /
``GenerateRequest`` / ``RerankRequest`` / ``VisionRequest`` — the host **fulfills**
it (expands ``${ENV}``, does the HTTP, scrubs the response) and returns a
``ModelResponse``, and the core parses it and resumes. Two FFI crossings, **no
callback** (SPEC-PORTS-v1).

The load-bearing invariant — carried by these types — is that **no credential ever
crosses into the core, in either direction**:

- **Request:** ``ModelAuth`` references creds by ``${ENV}`` header NAME only; the
  host expands them at the HTTP boundary. Query-param keys and request-signing
  (AWS SigV4 / Bedrock) are a NAMED host-side capability (``ModelAuth.sign``),
  never the core's — the core holds no signing key.
- **Response:** the fulfilled ``ModelResponse.body`` is the provider JSON with any
  reflected credential scrubbed by the host before it re-enters the core.

These types are the wire between the phases: frozen, forbidding unknown fields,
and credential-free by construction.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# One remote-model seam. The discriminator each ``ModelRequest`` subclass fixes.
ModelKind = Literal["embed", "generate", "rerank", "vision"]

# A provider-shaped JSON object (request body / response body). Kept loose on
# purpose: the protocol pins *where* the call happens, not each provider's wire —
# that is per-seam migration work.
JsonObject = dict[str, Any]


class ModelAuth(BaseModel):
    """How the host authenticates a request — by REFERENCE, never by value.

    ``headers`` maps header names to values that may embed ``${ENV}`` templates
    (e.g. ``{"Authorization": "Bearer ${OPENAI_API_KEY}"}``); the host expands
    them only at the HTTP boundary, so the secret's value never lives in the core.

    ``sign`` names a host-side signing/transform capability for auth that a header
    template can't express — a query-param key, or AWS SigV4 request signing. When
    set, the host runs that capability to mutate the core-built request at the
    boundary; the core never signs and holds no signing key. An empty ``ModelAuth``
    is a request that needs no auth (e.g. a local Ollama).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    headers: dict[str, str] = {}
    sign: str | None = None


class ModelRequest(BaseModel):
    """One credential-free, model-ready request the core emits for host fulfillment.

    ``kind`` discriminates the four seams; ``url`` + ``body`` are the fully-
    assembled, provider-shaped HTTP request the core builds (like
    ``VisionPayload``), carrying NO secret; ``auth`` references creds by ``${ENV}``
    name only. ``request_id`` is the sole key the fulfilled response is addressed
    back by. Subclasses fix ``kind``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    kind: ModelKind
    url: str
    body: JsonObject = {}
    auth: ModelAuth = ModelAuth()


class EmbedRequest(ModelRequest):
    """A dense/sparse embedding call (e.g. OpenAI ``/embeddings``)."""

    kind: Literal["embed"] = "embed"


class GenerateRequest(ModelRequest):
    """A text-generation call (e.g. OpenAI ``/chat/completions``)."""

    kind: Literal["generate"] = "generate"


class RerankRequest(ModelRequest):
    """A cross-encoder rerank call (e.g. a ``/rerank`` endpoint)."""

    kind: Literal["rerank"] = "rerank"


class VisionRequest(ModelRequest):
    """A figure-description call — an image + prompt as an OpenAI vision message."""

    kind: Literal["vision"] = "vision"


class ModelResponse(BaseModel):
    """The host's fulfilled, SANITIZED response the core parses and resumes on.

    ``body`` is the provider JSON with any reflected credential scrubbed;
    credential-free by construction — the fulfiller redacts before this object
    exists. Addressed back to its request by ``request_id``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    status: int
    body: JsonObject = {}
