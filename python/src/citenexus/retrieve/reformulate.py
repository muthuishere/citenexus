"""Query reformulation for multi-query retrieval (spec §10 / §11a, ADR-0013).

Cross-lingual retrieval misses are a top abstention cause: a French query over
English evidence aligns imperfectly in embedding space and shares zero BM25
tokens. The researched fix (tRAG / RAG-Fusion): rewrite the query in English
with a SMALL model, retrieve with BOTH the original and the reformulation, and
RRF-fuse the lists. The original query is always kept — translation can damage
exact tokens (names, IDs, clause numbers) that lexical retrieval needs.

The target was English-only until ADR-0013: that fixes "French question, English
corpus" and does nothing for "English question, Tamil corpus", where the token
sets are disjoint and lexical recall is measurably **zero**. The target is now a
parameter, defaulting to ``"en"`` — the byte-identical prompt, so the default path
is unchanged behaviour rather than a re-implementation of it.

The instance carries a **shared reformulation cache** keyed by (query, language), so
``ask()``, ``retrieve()``, and ``evaluate()`` (which asks per CSV row) pay the
model at most once per distinct question — including caching failures, so a dead
endpoint is not hammered.

Enhancement-only: any failure, an empty reply, or a reformulation identical to
the original returns ``None`` and retrieval proceeds single-query.
"""

from __future__ import annotations

import json
from typing import Protocol

from citenexus.http import DEFAULT_TRANSPORT, Transport


class Reformulator(Protocol):
    """The reformulation seam — structural, so test fakes satisfy it too.

    ``language`` is an ISO-639-1 code and defaults to ``"en"``, which is the exact
    behaviour this seam had before ADR-0013 made the target configurable.
    """

    def reformulate(self, query: str, language: str = "en") -> str | None: ...


_PROMPT_TEMPLATE = (
    "Rewrite the following search query in {language} for retrieving documents. "
    "Keep names, numbers, and technical identifiers exactly as written. "
    "Reply with ONLY the rewritten query, nothing else.\n\n"
    "Query: {query}"
)

# The pinned cross-port prompt contract (`conformance/prompts.json`) is the
# ENGLISH prompt, and generalising the target must not move it. So `_PROMPT` stays
# the rendered English string, byte-for-byte what it was before ADR-0013, and the
# template is what the runtime formats. `reformulate(q, "en")` sends exactly this.
_PROMPT = _PROMPT_TEMPLATE.replace("{language}", "English")


def _language_name(code: str) -> str:
    """The prompt-facing name for an ISO-639-1 code.

    Unknown codes pass through verbatim rather than raising: the capability
    refusal is ``lang/search.py``'s job and it runs first, at the ``ask`` /
    ``retrieve`` boundary. A reformulator handed an unusual code directly should
    still do something reasonable rather than explode inside a retrieval path.
    """
    from citenexus.lang.search import SEARCH_LANGUAGES

    language = SEARCH_LANGUAGES.get(code)
    return language.name if language is not None else code


class QueryReformulator:
    """Rewrite a query in a target language via a small injected model, cached.

    The cache is keyed by ``(query, language)`` so a fan-out across N languages
    costs at most N model calls per distinct question, shared by ``ask``,
    ``retrieve`` and ``evaluate``.
    """

    plugin_version = "query-reformulator-v1"

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
        # The shared reformulation cache: (query, language) -> rewrite (or None).
        self._cache: dict[tuple[str, str], str | None] = {}

    def _headers(self) -> dict[str, str]:
        # Auth + provider headers are the ENDPOINT layer's job (HttpEndpoint
        # transport); wire clients only speak JSON.
        return {"Content-Type": "application/json"}

    def reformulate(self, query: str, language: str = "en") -> str | None:
        """``query`` rewritten in ``language`` — or ``None`` when it adds nothing."""
        key = (query, language)
        if key in self._cache:
            return self._cache[key]
        result = self._reformulate_uncached(query, language)
        self._cache[key] = result
        return result

    def _reformulate_uncached(self, query: str, language: str) -> str | None:
        prompt = _PROMPT_TEMPLATE.format(query=query, language=_language_name(language))
        request = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }
        body = json.dumps(request).encode("utf-8")
        try:
            raw = self._transport(f"{self._base_url}/chat/completions", body, self._headers())
            content: str = json.loads(raw)["choices"][0]["message"]["content"]
        except Exception:
            return None
        rewritten = content.strip()
        if not rewritten or rewritten == query:
            return None
        return rewritten
