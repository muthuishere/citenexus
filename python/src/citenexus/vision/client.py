"""``OpenAICompatibleVision`` — the injected VL endpoint behind §9 vision.

CiteNexus bundles no models: image description comes from an injected,
OpenAI-compatible *vision* endpoint (Gemini's OpenAI-compat endpoint, GPT-4o, a
local VL server). This plugin base64-encodes the image bytes into an OpenAI
``image_url`` data URI, posts ``{model, messages, temperature}`` to
``{base_url}/chat/completions``, and asks the model for a JSON description with
the fields a figure Evidence Unit needs.

It satisfies the ``VisionPlugin.describe`` contract (returns a mapping that
``vision.describe_image`` shapes into a ``VisionRecord``), so it drops into the
conditional-vision pipeline exactly where ``FakeVision`` sits in tests. Same
seam as the other model clients: injected ``transport`` (stdlib-urllib default,
no new deps), temperature always sent (0.0), key only via ``api_key_env``.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

from citenexus.http import DEFAULT_TRANSPORT, Transport

_VISION_PROMPT = (
    "Describe this image for a document search index, covering every aspect so a "
    "later question about the image can be answered from your description alone. "
    "Reply with ONLY a JSON object with keys: "
    "short_caption (string), "
    "detailed_description (string — if the image is a chart/diagram/table, describe "
    "its layout and structure, every visible number/label/axis value, the colors used "
    "and what they encode if there is a legend, and the spatial relationships between "
    "elements), "
    "objects (array of strings), "
    "relationships (array of strings), "
    "ocr_text (string of any text visible in the image, verbatim), "
    "data_values (array of objects {label, value} for any numeric/tabular values shown "
    "in a chart, graph, or table-as-image; empty array if none), "
    "image_type (one of: photo, chart, diagram, screenshot, table, handwriting, logo, "
    "other). Do not add prose outside the JSON."
)


def _image_bytes(image: Any) -> bytes:
    """Best-effort extraction of raw image bytes from the argument.

    Accepts raw ``bytes`` directly; otherwise looks for a ``.data`` / ``.bytes``
    attribute (an image object that carries its own bytes). Raises otherwise —
    the caller is responsible for loading bytes from a ``blob_key`` first.
    """
    if isinstance(image, bytes | bytearray):
        return bytes(image)
    for attr in ("data", "bytes"):
        value = getattr(image, attr, None)
        if isinstance(value, bytes | bytearray):
            return bytes(value)
    raise TypeError(
        "OpenAICompatibleVision.describe needs image bytes (or an object with a "
        f".data/.bytes attribute), got {type(image).__name__}"
    )


class OpenAICompatibleVision:
    """Image description over an OpenAI-compatible vision ``/chat/completions``."""

    plugin_version = "openai-vision-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = 8192,
        mime_type: str = "image/png",
        transport: Transport | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._mime_type = mime_type
        self._transport: Transport = transport or DEFAULT_TRANSPORT
        # First-class auth/provider headers (toolnexus style): ``${ENV}`` templates
        # resolved by the transport at call time, never held as values here.
        self._extra_headers = dict(headers or {})

    @property
    def _endpoint(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        # Wire clients speak JSON + any caller-supplied auth/provider headers
        # (``${ENV}`` templates, resolved by the transport at call time).
        return {"Content-Type": "application/json", **self._extra_headers}

    def describe(self, image_region: Any) -> dict[str, Any]:
        """Describe an image's bytes; returns the mapping ``describe_image`` shapes.

        The standalone (non-two-phase) entry: encodes the bytes with this client's
        configured ``mime_type`` and the pinned prompt, then completes.
        """
        raw = _image_bytes(image_region)
        data_uri = f"data:{self._mime_type};base64,{base64.b64encode(raw).decode()}"
        return self._complete(data_uri, _VISION_PROMPT)

    def describe_payload(self, image_url: str, prompt: str) -> dict[str, Any]:
        """Fulfill a two-phase `PendingVisionRequest`: POST the core's already-assembled
        ``image_url`` data URI + prompt **verbatim** (no re-encode), so the reference
        host sends exactly the emitted payload the ports reproduce."""
        return self._complete(image_url, prompt)

    def _complete(self, image_url: str, prompt: str) -> dict[str, Any]:
        """POST one prompt + image_url to ``/chat/completions`` and parse the reply."""
        request: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "temperature": self._temperature,
        }
        if self._max_tokens is not None:
            request["max_tokens"] = self._max_tokens
        body = json.dumps(request).encode("utf-8")
        payload = json.loads(self._transport(self._endpoint, body, self._headers()))
        content: str = payload["choices"][0]["message"]["content"]
        return _parse_description(content)


def _parse_description(content: str) -> dict[str, Any]:
    """Parse the model's reply into a record mapping.

    A well-behaved model returns JSON; a model that ignores the instruction and
    returns prose still yields a usable ``short_caption`` rather than failing.
    """
    text = content.strip()
    if text.startswith("```"):
        # strip a ```json … ``` fence if present
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return {"short_caption": content.strip()}
    if not isinstance(parsed, dict):
        return {"short_caption": content.strip()}
    return parsed
