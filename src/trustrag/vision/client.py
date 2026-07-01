"""``OpenAICompatibleVision`` — the injected VL endpoint behind §9 vision.

TrustRAG bundles no models: image description comes from an injected,
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
import os
from typing import Any

from trustrag.answer.generator import Transport, _urllib_transport

_VISION_PROMPT = (
    "Describe this image for a document search index. Reply with ONLY a JSON "
    "object with keys: short_caption (string), detailed_description (string), "
    "objects (array of strings), relationships (array of strings), ocr_text "
    "(string of any text visible in the image). Do not add prose outside the JSON."
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
        api_key_env: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = 512,
        mime_type: str = "image/png",
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key_env = api_key_env
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._mime_type = mime_type
        self._transport: Transport = transport or _urllib_transport

    @property
    def _endpoint(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key_env:
            key = os.environ.get(self._api_key_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def describe(self, image_region: Any) -> dict[str, Any]:
        """Describe an image; returns the record mapping ``describe_image`` shapes."""
        raw = _image_bytes(image_region)
        data_uri = f"data:{self._mime_type};base64,{base64.b64encode(raw).decode()}"
        request: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VISION_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_uri}},
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
