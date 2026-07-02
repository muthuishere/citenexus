"""S3-native, S3-*scalable* wiki over Evidence Units (§10b).

Wiki pages are navigation aids, never citation targets. Each hit resolves to the
page's underlying EU refs before the answer path sees it.

Built for "very big" corpora — nothing is loaded or rewritten wholesale:

- ``wiki/index.json`` — the LIGHT manifest (page_id/title/keywords/links/summary,
  **no eu_refs**). The only object a query reads.
- ``wiki/pages/{id}.json`` — one full page per object, fetched only when matched.
- ``wiki/pages/{id}.md`` + ``wiki/index.md`` — the human-browsable tree.
- ``wiki/log.md`` — Karpathy-style append-only journal of ingests/rebuilds.

Growth is **incremental**: ``integrate_document`` upserts one document's page
and the light index — no full-wiki rebuild on ingest. ``build_from_store``
remains the full (re)build, and is where the LLM distiller runs (enhancement-
only; ``None`` degrades to deterministic pages). Legacy single-blob
``pages.json`` wikis still load.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

from citenexus.answer.verify import content_tokens
from citenexus.domain.partition import PartitionPath
from citenexus.storage.backend import StorageBackend
from citenexus.storage.paths import Layer, layer_prefix
from citenexus.storage.protocols import VectorStore

if TYPE_CHECKING:
    from citenexus.wiki.distill import WikiDistiller

_LEGACY_FILE = "pages.json"
_INDEX_JSON = "index.json"
_INDEX_MD = "index.md"
_LOG_MD = "log.md"


class WikiPage(BaseModel):
    """One generated navigation page (per-document or cross-document concept)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_id: str
    title: str
    summary: str
    keywords: tuple[str, ...]
    eu_refs: tuple[str, ...]
    # Cross-references to other page ids ([[links]]). Defaults empty so
    # pages written before this field existed still load.
    links: tuple[str, ...] = ()

    def index_entry(self) -> dict[str, Any]:
        """The LIGHT index projection — everything a query needs, no eu_refs."""
        return {
            "page_id": self.page_id,
            "title": self.title,
            "summary": self.summary,
            "keywords": list(self.keywords),
            "links": list(self.links),
        }


class WikiLintIssue(BaseModel):
    """One typed wiki maintenance finding (the §10b ``lint`` pass)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["dangling_link", "orphan_page", "missing_eu"]
    page_id: str
    ref: str = ""


class WikiStore:
    """Persist and load wiki pages for one partition — per-page S3 objects."""

    def __init__(
        self,
        backend: StorageBackend,
        partition: PartitionPath,
        *,
        distiller: WikiDistiller | None = None,
    ) -> None:
        self._backend = backend
        self._partition = partition
        self._distiller = distiller

    # ------------------------------------------------------------------ keys
    @property
    def _prefix(self) -> str:
        return f"{layer_prefix(Layer.knowledge, self._partition)}/wiki"

    @property
    def key(self) -> str:  # legacy single-blob manifest (read-only fallback)
        return f"{self._prefix}/{_LEGACY_FILE}"

    @property
    def index_json_key(self) -> str:
        return f"{self._prefix}/{_INDEX_JSON}"

    @property
    def index_key(self) -> str:
        return f"{self._prefix}/{_INDEX_MD}"

    @property
    def log_key(self) -> str:
        return f"{self._prefix}/{_LOG_MD}"

    def page_json_key(self, page_id: str) -> str:
        return f"{self._prefix}/pages/{_slug(page_id)}.json"

    def page_key(self, page_id: str) -> str:
        return f"{self._prefix}/pages/{_slug(page_id)}.md"

    # ------------------------------------------------------------- light index
    def load_index(self) -> list[dict[str, Any]]:
        """The light manifest — the ONLY object a query loads up front."""
        if self._backend.exists(self.index_json_key):
            entries: list[dict[str, Any]] = self._backend.get_json(self.index_json_key)
            return entries
        # Legacy single-blob wikis: project the light entries from pages.json.
        return [page.index_entry() for page in self._load_legacy()]

    def load_page(self, page_id: str) -> WikiPage | None:
        """Fetch ONE page object; falls back to the legacy blob when present."""
        key = self.page_json_key(page_id)
        if self._backend.exists(key):
            return WikiPage.model_validate(self._backend.get_json(key))
        for page in self._load_legacy():
            if page.page_id == page_id:
                return page
        return None

    def load(self) -> tuple[WikiPage, ...]:
        """All pages — maintenance/lint use only; queries use the light index."""
        if self._backend.exists(self.index_json_key):
            pages = []
            for entry in self.load_index():
                page = self.load_page(str(entry["page_id"]))
                if page is not None:
                    pages.append(page)
            return tuple(pages)
        return self._load_legacy()

    def _load_legacy(self) -> tuple[WikiPage, ...]:
        if not self._backend.exists(self.key):
            return ()
        raw = self._backend.get_json(self.key)
        return tuple(WikiPage.model_validate(item) for item in raw)

    # ---------------------------------------------------------------- builds
    def integrate_document(self, document_id: str, store: VectorStore) -> WikiPage:
        """Incrementally upsert ONE document's page — no full-wiki rebuild.

        The Karpathy compounding move at library scale: an ingest touches its
        own page + the light index + the log, never the whole wiki.
        """
        rows = [
            row for row in store.scan() if str(row.get("document_id", row["eu_id"])) == document_id
        ]
        page = _deterministic_page(document_id, rows)
        self._upsert_pages((page,))
        self._log(f"ingest | {document_id}")
        return page

    def build_from_store(self, store: VectorStore) -> tuple[WikiPage, ...]:
        """Full (re)build — the distiller path, and the crawl/bulk entry point."""
        rows_by_doc: dict[str, list[dict[str, object]]] = {}
        for row in store.scan():
            rows_by_doc.setdefault(str(row.get("document_id", row["eu_id"])), []).append(row)

        # LLM distillation first (when injected) — enhancement-only, so any
        # failure (None) falls through to the deterministic pages below.
        if self._distiller is not None:
            pages_input = {
                document_id: tuple((str(row["eu_id"]), str(row.get("text", ""))) for row in rows)
                for document_id, rows in sorted(rows_by_doc.items())
            }
            distilled = self._distiller.distill(pages_input)
            if distilled:
                self.save(distilled)
                self._log(f"rebuild | distilled {len(distilled)} pages")
                return distilled

        pages = tuple(
            _deterministic_page(document_id, rows)
            for document_id, rows in sorted(rows_by_doc.items())
        )
        self.save(pages)
        self._log(f"rebuild | deterministic {len(pages)} pages")
        return pages

    def save(self, pages: tuple[WikiPage, ...]) -> None:
        """Replace the wiki with ``pages`` (per-page objects + light index)."""
        # Clear stale page files from a previous build (trailing slash keeps
        # the sibling index/log objects out of the prefix match).
        self._backend.delete_prefix(f"{self._prefix}/pages/")
        self._upsert_pages(pages, replace_index=True)

    def _upsert_pages(self, pages: tuple[WikiPage, ...], *, replace_index: bool = False) -> None:
        by_id = {} if replace_index else {e["page_id"]: e for e in self.load_index()}
        for page in pages:
            self._backend.put_json(self.page_json_key(page.page_id), page.model_dump(mode="json"))
            self._backend.put_bytes(self.page_key(page.page_id), _page_markdown(page))
            by_id[page.page_id] = page.index_entry()
        entries = [by_id[page_id] for page_id in sorted(by_id)]
        self._backend.put_json(self.index_json_key, entries)
        self._backend.put_bytes(self.index_key, _index_markdown(entries))

    def _log(self, message: str) -> None:
        """Append one journal line (Karpathy's log.md), S3-native."""
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        line = f"## [{stamp}] {message}\n"
        existing = (
            self._backend.get_bytes(self.log_key)
            if self._backend.exists(self.log_key)
            else b"# Wiki Log\n\n"
        )
        self._backend.put_bytes(self.log_key, existing + line.encode("utf-8"))

    # ------------------------------------------------------------------ lint
    def lint(self, store: VectorStore) -> list[WikiLintIssue]:
        """Typed maintenance findings over the saved pages. Pure — no model.

        - ``dangling_link``: a ``[[link]]`` whose target page id doesn't exist.
        - ``orphan_page``: a page with no ``eu_refs`` (nothing to resolve to —
          it can never contribute evidence, only dead navigation).
        - ``missing_eu``: an ``eu_ref`` absent from the leaf store's ``scan()``.
        """
        pages = self.load()
        page_ids = {page.page_id for page in pages}
        known_eus = {str(row["eu_id"]) for row in store.scan()}
        issues: list[WikiLintIssue] = []
        for page in pages:
            for link in page.links:
                if link not in page_ids:
                    issues.append(
                        WikiLintIssue(kind="dangling_link", page_id=page.page_id, ref=link)
                    )
            if not page.eu_refs:
                issues.append(WikiLintIssue(kind="orphan_page", page_id=page.page_id))
            for eu_ref in page.eu_refs:
                if eu_ref not in known_eus:
                    issues.append(
                        WikiLintIssue(kind="missing_eu", page_id=page.page_id, ref=eu_ref)
                    )
        return issues


def _deterministic_page(document_id: str, rows: list[dict[str, object]]) -> WikiPage:
    texts = [str(row.get("text", "")) for row in rows]
    return WikiPage(
        page_id=f"wiki:{document_id}",
        title=document_id,
        summary=_summary(texts),
        keywords=_top_keywords(" ".join(texts)),
        eu_refs=tuple(str(row["eu_id"]) for row in rows),
    )


def _slug(page_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", page_id).strip("-") or "page"


def _page_markdown(page: WikiPage) -> bytes:
    lines = [f"# {page.title}", "", page.summary, ""]
    if page.keywords:
        lines += [f"**Keywords:** {', '.join(page.keywords)}", ""]
    if page.links:
        lines += [f"**Links:** {' '.join(f'[[{link}]]' for link in page.links)}", ""]
    lines.append("**Evidence Units:**")
    lines += [f"- {eu_ref}" for eu_ref in page.eu_refs]
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _index_markdown(entries: list[dict[str, Any]]) -> bytes:
    lines = ["# Wiki Index", ""]
    lines += [f"- [{entry['title']}](pages/{_slug(str(entry['page_id']))}.md)" for entry in entries]
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _top_keywords(text: str, limit: int = 12) -> tuple[str, ...]:
    counts = Counter(content_tokens(text))
    return tuple(token for token, _count in counts.most_common(limit))


def _summary(texts: list[str], max_chars: int = 240) -> str:
    joined = " ".join(texts).strip()
    if len(joined) <= max_chars:
        return joined
    return joined[: max_chars - 1].rstrip() + "."
