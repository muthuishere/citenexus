"""LLM wiki distillation — Karpathy-style concept pages over the corpus (§10b).

The deterministic wiki (per-document truncation summaries + token-count
keywords) is a navigation stand-in. The spec's v5 commitment is an LLM-Wiki:
a SMALL model reads the corpus's Evidence Units grouped by document and
distills **cross-referenced pages** — per-document summaries plus concept
pages for topics that span documents — each carrying ``[[links]]`` to related
pages and the EU ids it is grounded in.

NAVIGATE-NOT-CITE INVARIANT: distilled pages are navigation aids only. A page
is never a citation target; every wiki hit resolves down to the bbox-cited
Evidence Units in ``eu_refs``. To keep that sound, ``eu_refs`` returned by the
model are sanitized against the actual corpus — an id the model invented is
dropped, never surfaced.

Distillation is an enhancement, never a hard dependency: any transport failure,
malformed reply, or empty page set returns ``None`` and the store degrades to
its deterministic pages (same pattern as ``evidence/contextualize.py``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Protocol

from citenexus.answer.generator import Transport, _urllib_transport
from citenexus.wiki.store import WikiPage

# The distiller input: document_id -> ordered (eu_id, text) pairs.
PagesInput = Mapping[str, Sequence[tuple[str, str]]]


class WikiDistiller(Protocol):
    """The wiki-distillation seam — structural, so test fakes satisfy it too."""

    def distill(self, pages_input: PagesInput) -> tuple[WikiPage, ...] | None: ...


_PROMPT = (
    "You are compiling a navigation wiki over a document corpus. Below are the "
    "documents, each listing its Evidence Units as `eu_id: text`.\n"
    "Produce cross-referenced wiki pages:\n"
    "- one summary page per document, and\n"
    "- concept pages for topics that span multiple documents.\n"
    "Each page needs: a stable lowercase hyphenated page_id, a title, a 1-3 "
    "sentence summary, 3-12 keywords, links (page_ids of related pages), and "
    "eu_refs (ONLY Evidence Unit ids that appear below — the page must be "
    "grounded in them).\n"
    "Reply with ONLY this JSON, nothing else:\n"
    '{{"pages": [{{"page_id": "...", "title": "...", "summary": "...", '
    '"keywords": ["..."], "links": ["..."], "eu_refs": ["..."]}}]}}\n\n'
    "{corpus}"
)
# Caps keep the small-model call cheap on a large corpus.
_MAX_EU_CHARS = 500
_MAX_CORPUS_CHARS = 24_000


class LLMWikiDistiller:
    """Distill corpus EUs into cross-referenced wiki pages via a small model."""

    plugin_version = "llm-wiki-distiller-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_env: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        # Store only the env-var *name*, never the secret value.
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key_env = api_key_env
        self._transport: Transport = transport or _urllib_transport

    def _headers(self) -> dict[str, str]:
        import os

        headers = {"Content-Type": "application/json"}
        if self._api_key_env:
            key = os.environ.get(self._api_key_env)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def distill(self, pages_input: PagesInput) -> tuple[WikiPage, ...] | None:
        """Distilled pages for the corpus — or ``None`` on any failure."""
        if not pages_input:
            return None
        prompt = _PROMPT.format(corpus=_corpus_block(pages_input))
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
            return None
        known_eus = {eu_id for units in pages_input.values() for eu_id, _text in units}
        return _parse_pages(str(content), known_eus)


def _corpus_block(pages_input: PagesInput) -> str:
    lines: list[str] = []
    total = 0
    for document_id in sorted(pages_input):
        lines.append(f"# Document: {document_id}")
        for eu_id, text in pages_input[document_id]:
            line = f"{eu_id}: {text[:_MAX_EU_CHARS]}"
            total += len(line)
            if total > _MAX_CORPUS_CHARS:
                lines.append("(corpus truncated)")
                return "\n".join(lines)
            lines.append(line)
    return "\n".join(lines)


def _parse_pages(content: str, known_eus: set[str]) -> tuple[WikiPage, ...] | None:
    """Parse the model's JSON reply (with a prose fallback), sanitized.

    The prose fallback rescues a compliant JSON object wrapped in chatter
    ("Here is the wiki: {...}"). Sanitization drops eu_refs the model invented
    — the navigate-not-cite invariant needs every ref to resolve to a real EU.
    """
    parsed = _load_json(content)
    if not isinstance(parsed, dict):
        return None
    raw_pages = parsed.get("pages")
    if not isinstance(raw_pages, list):
        return None
    pages: list[WikiPage] = []
    seen: set[str] = set()
    for item in raw_pages:
        page = _page_of(item, known_eus)
        if page is None or page.page_id in seen:
            continue
        seen.add(page.page_id)
        pages.append(page)
    return tuple(pages) or None


def _load_json(content: str) -> object:
    try:
        return json.loads(content)
    except ValueError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(content[start : end + 1])
        except ValueError:
            return None


def _page_of(item: object, known_eus: set[str]) -> WikiPage | None:
    if not isinstance(item, dict):
        return None
    page_id = str(item.get("page_id", "")).strip()
    title = str(item.get("title", "")).strip()
    if not page_id or not title:
        return None
    return WikiPage(
        page_id=page_id,
        title=title,
        summary=str(item.get("summary", "")).strip(),
        keywords=_str_tuple(item.get("keywords")),
        links=tuple(link.strip("[]") for link in _str_tuple(item.get("links"))),
        eu_refs=tuple(ref for ref in _str_tuple(item.get("eu_refs")) if ref in known_eus),
    )


def _str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v).strip() for v in value if str(v).strip())
