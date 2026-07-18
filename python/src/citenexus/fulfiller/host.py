"""Fulfill phase — the reference host fulfiller (spec: model-fulfiller, §2/§3).

The host makes every authenticated model call so the credential never enters the
core. ``ModelFulfiller`` is the reference: given a core-emitted ``ModelRequest``,
it expands ``${ENV}`` header creds at the HTTP boundary, optionally runs a named
host-side signing capability (query-param keys / AWS SigV4), does the HTTP via the
shared ``Transport``, and **scrubs the response** before handing it back — because
provider 401/debug bodies reflect the ``Authorization`` header or a ``?key=`` param.

Two invariants live here, one per direction:

- **Request:** ``${ENV}`` is expanded only inside ``fulfill`` and only into the
  headers handed to the transport. As a guard, an emitted request whose body/URL
  already embeds a header-referenced secret value is refused before any HTTP — the
  emit-carries-names-only invariant is enforced, not merely documented.
- **Response:** every secret materialized at this boundary (expanded ``${ENV}``
  header values + any a signer declares) is redacted from the parsed response, and
  echoed auth header/param keys are dropped, so a reflected credential never
  re-enters a core value or log.

A port in another language implements this same phase as a thin "expand → POST →
scrub" call; the Python reference reuses the shared ``http`` transport seam.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple, Protocol

from citenexus.domain.model import JsonObject, ModelRequest, ModelResponse
from citenexus.http import DEFAULT_TRANSPORT, Transport, expand_env

_LOG = logging.getLogger("citenexus.fulfiller")

_REDACTION = "[REDACTED]"

# ``${ENV_VAR}`` reference inside a header template — same grammar as ``http``.
_ENV_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")

# Header / param KEY names whose value is redacted wholesale when a response echoes
# it back — defense-in-depth on top of the exact-value substring scrub below.
_AUTH_KEYS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "api_key",
        "apikey",
        "access_token",
        "x-amz-security-token",
    }
)


class SignedRequest(NamedTuple):
    """What a host-side signer returns: the mutated ``url``/``headers`` and any
    secret values it materialized, declared so the fulfiller scrubs them from the
    response. The core sees none of this."""

    url: str
    headers: dict[str, str]
    secrets: tuple[str, ...] = ()


# A named host-side capability: sign/transform the core-built request at the HTTP
# boundary (query-param keys, AWS SigV4). Receives the request + the already-
# expanded headers; returns the mutated request. The signing key stays host-side.
Signer = Callable[[ModelRequest, dict[str, str]], SignedRequest]


class Fulfiller(Protocol):
    """The host-side contract: turn an emitted request into a parsed response."""

    def fulfill(self, request: ModelRequest) -> ModelResponse: ...


def _referenced_env_values(templates: Mapping[str, str]) -> set[str]:
    """The live values of every ``${ENV}`` referenced in the header templates —
    the secrets this boundary will materialize, gathered to scrub the response."""
    values: set[str] = set()
    for template in templates.values():
        for name in _ENV_RE.findall(template):
            value = os.environ.get(name, "")
            if value:
                values.add(value)
    return values


def _scrub(obj: Any, secrets: frozenset[str]) -> Any:
    """Recursively redact reflected credentials: drop any auth-named key's value,
    and replace every known secret substring anywhere in a string."""
    if isinstance(obj, dict):
        return {
            key: _REDACTION if str(key).lower() in _AUTH_KEYS else _scrub(value, secrets)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_scrub(item, secrets) for item in obj]
    if isinstance(obj, str):
        for secret in secrets:
            if secret and secret in obj:
                obj = obj.replace(secret, _REDACTION)
        return obj
    return obj


class ModelFulfiller:
    """The reference host fulfiller: expand ``${ENV}`` → (sign) → HTTP → scrub."""

    def __init__(
        self,
        *,
        transport: Transport = DEFAULT_TRANSPORT,
        signers: Mapping[str, Signer] | None = None,
    ) -> None:
        self._transport = transport
        self._signers = dict(signers or {})

    def fulfill(self, request: ModelRequest) -> ModelResponse:
        # Secrets this boundary will materialize from the header templates.
        secrets = _referenced_env_values(request.auth.headers)

        # Request-direction guard: the emit must carry ${ENV} NAMES, never values.
        emitted = request.url + json.dumps(request.body, sort_keys=True)
        if any(secret in emitted for secret in secrets):
            raise ValueError(
                "emitted request embeds a credential value; the core must reference "
                "creds by ${ENV} name only"
            )

        # Expand ${ENV} ONLY here, ONLY into the headers handed to the transport.
        url = request.url
        headers = {name: expand_env(value) for name, value in request.auth.headers.items()}

        if request.auth.sign is not None:
            signer = self._signers[request.auth.sign]  # KeyError = unknown capability
            signed = signer(request, headers)
            url, headers = signed.url, signed.headers
            secrets |= {secret for secret in signed.secrets if secret}

        body_bytes = json.dumps(request.body).encode("utf-8")
        raw = self._transport(url, body_bytes, headers)
        parsed = json.loads(raw.decode("utf-8"))
        clean = _scrub(parsed, frozenset(secrets))
        body: JsonObject = clean if isinstance(clean, dict) else {"data": clean}

        # Secret-free by construction: only the request_id/kind reach the log.
        _LOG.debug("fulfilled %s request %s", request.kind, request.request_id)
        return ModelResponse(request_id=request.request_id, status=200, body=body)
