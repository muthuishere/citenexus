"""Contextual retrieval — situate each chunk with a small model (spec §7).

Anthropic's Contextual Retrieval: before embedding/indexing, prepend a short
(50-100 token) LLM-generated blurb that situates the chunk in its document. It
cut top-20 retrieval failures ~35% (embeddings) / ~49% (+BM25) / ~67% (+rerank).
Because the job is cheap and high-volume, it uses a SMALL model (Anthropic uses
Haiku); here it's an injected, OpenAI-compatible endpoint at temperature 0.

SAFETY INVARIANT (legal/medical): the context enriches only the *indexed text*.
The caller keeps the verbatim chunk as the citation ``passage`` — the model's
words are a retrieval aid and must never become the cited source. This module
returns ``context + "\\n" + chunk``; the ingest layer indexes that but cites the
raw chunk.

Contextualization is an enhancement, never a hard dependency: any failure or an
empty reply degrades to the bare chunk (retrieval still works, just un-enriched).
"""

from __future__ import annotations

import json

from citenexus.http import DEFAULT_TRANSPORT, Transport

_PROMPT = (
    "Here is a document, then a chunk from it. Give a short (one sentence, "
    "50-100 tokens) context that situates the chunk within the document to "
    "improve search retrieval — name the document/section/entity/time it belongs "
    "to. Answer with ONLY that context sentence, nothing else.\n\n"
    "<document>\n{document}\n</document>\n\n"
    "<chunk>\n{chunk}\n</chunk>"
)
# Cap the document sent to the small model so a huge source stays cheap.
_MAX_DOC_CHARS = 8000


class Contextualizer:
    """Generate a situating prefix for a chunk via a small injected model."""

    plugin_version = "contextualizer-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._transport: Transport = transport or DEFAULT_TRANSPORT

    def _headers(self) -> dict[str, str]:
        # Auth + provider headers are the ENDPOINT layer's job (HttpEndpoint
        # transport); wire clients only speak JSON.
        return {"Content-Type": "application/json"}

    def contextualize(self, *, chunk: str, document: str) -> str:
        """Return ``context + "\\n" + chunk`` — or the bare chunk on any failure."""
        prompt = _PROMPT.format(document=document[:_MAX_DOC_CHARS], chunk=chunk)
        request = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }
        body = json.dumps(request).encode("utf-8")
        try:
            raw = self._transport(f"{self._base_url}/chat/completions", body, self._headers())
            content = json.loads(raw)["choices"][0]["message"]["content"]
        except Exception:
            return chunk
        context = content.strip()
        if not context:
            return chunk
        return f"{context}\n{chunk}"
