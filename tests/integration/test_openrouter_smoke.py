"""Opt-in OpenRouter regression smoke.

This test is skipped unless an OpenRouter key is available. The secret is loaded
from the process environment first, then from the gitignored local dev vault:
`infra/vault/dev/openrouter.env`.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_VAULT_ENV = _ROOT / "infra" / "vault" / "dev" / "openrouter.env"
_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def _openrouter_key() -> str | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    if not _VAULT_ENV.exists():
        return None
    for line in _VAULT_ENV.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name == "OPENROUTER_API_KEY" and value.strip():
            return value.strip().strip('"').strip("'")
    return None


@pytest.mark.integration
def test_openrouter_chat_completion_smoke() -> None:
    key = _openrouter_key()
    if key is None:
        pytest.skip("OPENROUTER_API_KEY not set and infra/vault/dev/openrouter.env absent")

    body = json.dumps(
        {
            "model": "openai/gpt-4o-mini",
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with exactly: TrustRAG regression OK",
                }
            ],
            "temperature": 0,
            "max_tokens": 16,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/muthuishere/trustrag",
            "X-Title": "TrustRAG regression",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    content = payload["choices"][0]["message"]["content"]
    assert "TrustRAG regression OK" in content
