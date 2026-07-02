"""OpenAICompatibleVision — describe an image over a VL endpoint (§9).

Mirrors the generator/embedding seam: injected ``transport``, stdlib-urllib
default, key only via ``api_key_env`` → Authorization header, temperature always
sent. The image bytes are base64-encoded into an OpenAI ``image_url`` data URI;
the model's JSON description is returned as the mapping ``describe_image`` shapes
into a ``VisionRecord``. It satisfies the ``VisionPlugin.describe`` contract.
"""

from __future__ import annotations

import base64
import json

import pytest

from citenexus.vision.client import OpenAICompatibleVision

_PNG = b"\x89PNG\r\n\x1a\n fake image bytes"


class RecordingTransport:
    def __init__(self, description: dict[str, object] | None = None) -> None:
        self.description = description or {
            "short_caption": "Revenue chart",
            "detailed_description": "A line chart of revenue over four quarters.",
            "objects": ["axis", "line"],
            "relationships": ["revenue rises each quarter"],
            "ocr_text": "Q1 Q2 Q3 Q4",
        }
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.calls.append((url, body, dict(headers)))
        content = json.dumps(self.description)
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

    @property
    def last_body(self) -> dict[str, object]:
        body: dict[str, object] = json.loads(self.calls[-1][1])
        return body


def _vision(t: RecordingTransport, *, api_key_env: str | None = None) -> OpenAICompatibleVision:
    return OpenAICompatibleVision(
        base_url="http://vl.test/v1",
        model="gemini-2.5-flash",
        api_key_env=api_key_env,
        transport=t,
    )


def test_plugin_version() -> None:
    assert OpenAICompatibleVision.plugin_version == "openai-vision-v1"


def test_describe_returns_record_fields() -> None:
    t = RecordingTransport()
    out = _vision(t).describe(_PNG)
    assert out["short_caption"] == "Revenue chart"
    assert "axis" in out["objects"]
    assert out["ocr_text"] == "Q1 Q2 Q3 Q4"


def test_posts_image_as_base64_data_uri() -> None:
    t = RecordingTransport()
    _vision(t).describe(_PNG)
    messages = t.last_body["messages"]
    assert isinstance(messages, list)
    blob = json.dumps(messages)
    assert "data:image/" in blob
    assert base64.b64encode(_PNG).decode() in blob


def test_temperature_zero_sent() -> None:
    t = RecordingTransport()
    _vision(t).describe(_PNG)
    assert t.last_body["temperature"] == 0.0


def test_non_json_content_falls_back_to_caption() -> None:
    def plain_text(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        return json.dumps({"choices": [{"message": {"content": "Just a plain sentence."}}]}).encode(
            "utf-8"
        )

    out = OpenAICompatibleVision(
        base_url="http://vl.test/v1", model="m", transport=plain_text
    ).describe(_PNG)
    # A model that ignores the JSON instruction still yields a usable caption.
    assert out["short_caption"] == "Just a plain sentence."


def test_api_key_only_in_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-not-real"
    monkeypatch.setenv("CITENEXUS_VISION_KEY", secret)
    t = RecordingTransport()
    _vision(t, api_key_env="CITENEXUS_VISION_KEY").describe(_PNG)
    _, body, headers = t.calls[-1]
    assert headers["Authorization"] == f"Bearer {secret}"
    assert secret not in body.decode("utf-8")
