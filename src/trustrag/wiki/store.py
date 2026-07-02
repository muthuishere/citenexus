"""S3-native wiki/navigation pages over Evidence Units.

Wiki pages are navigation aids, never citation targets. Each hit resolves to the
page's underlying EU refs before the answer path sees it.

Two builders share this store:

- **Deterministic** (no distiller): one page per document — truncation summary,
  token-count keywords. Always available, model-free.
- **LLM-distilled** (``distiller=`` injected): Karpathy-style cross-referenced
  concept pages with ``[[links]]`` between page ids. Enhancement-only — a
  distiller returning ``None`` degrades to the deterministic pages.

Either way the store persists ``pages.json`` (the machine manifest the
retriever reads) AND a browsable Markdown tree (``wiki/index.md`` +
``wiki/pages/<page>.md``) so a human can walk the wiki straight from S3.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from trustrag.answer.verify import content_tokens
from trustrag.domain.partition import PartitionPath
from trustrag.storage.backend import StorageBackend
from trustrag.storage.paths import Layer, layer_prefix
from trustrag.storage.protocols import VectorStore

if TYPE_CHECKING:
    from trustrag.wiki.distill import WikiDistiller

_WIKI_FILE = "pages.json"
_INDEX_FILE = "index.md"


class WikiPage(BaseModel):
    """One generated navigation page (per-document or cross-document concept)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_id: str
    title: str
    summary: str
    keywords: tuple[str, ...]
    eu_refs: tuple[str, ...]
    # Cross-references to other page ids ([[links]]). Defaults empty so
    # pages.json written before this field existed still loads.
    links: tuple[str, ...] = ()


class WikiLintIssue(BaseModel):
    """One typed wiki maintenance finding (the §10b ``lint`` pass)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["dangling_link", "orphan_page", "missing_eu"]
    page_id: str
    ref: str = ""


class WikiStore:
    """Persist and load wiki pages for one partition."""

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

    @property
    def _prefix(self) -> str:
        return f"{layer_prefix(Layer.knowledge, self._partition)}/wiki"

    @property
    def key(self) -> str:
        return f"{self._prefix}/{_WIKI_FILE}"

    @property
    def index_key(self) -> str:
        return f"{self._prefix}/{_INDEX_FILE}"

    def page_key(self, page_id: str) -> str:
        return f"{self._prefix}/pages/{_slug(page_id)}.md"

    def build_from_store(self, store: VectorStore) -> tuple[WikiPage, ...]:
        rows_by_doc: dict[str, list[dict[str, object]]] = {}
        for row in store.scan():
            rows_by_doc.setdefault(str(row.get("document_id", row["eu_id"])), []).append(row)

        # LLM distillation first (when injected) — enhancement-only, so any
        # failure (None) falls through to the deterministic pages below.
        if self._distiller is not None:
            pages_input = {
                document_id: tuple(
                    (str(row["eu_id"]), str(row.get("text", ""))) for row in rows
                )
                for document_id, rows in sorted(rows_by_doc.items())
            }
            distilled = self._distiller.distill(pages_input)
            if distilled:
                self.save(distilled)
                return distilled

        pages: list[WikiPage] = []
        for document_id, rows in sorted(rows_by_doc.items()):
            texts = [str(row.get("text", "")) for row in rows]
            keywords = _top_keywords(" ".join(texts))
            pages.append(
                WikiPage(
                    page_id=f"wiki:{document_id}",
                    title=document_id,
                    summary=_summary(texts),
                    keywords=keywords,
                    eu_refs=tuple(str(row["eu_id"]) for row in rows),
                )
            )
        self.save(tuple(pages))
        return tuple(pages)

    def save(self, pages: tuple[WikiPage, ...]) -> None:
        self._backend.put_json(self.key, [page.model_dump(mode="json") for page in pages])
        self._write_markdown(pages)

    def load(self) -> tuple[WikiPage, ...]:
        if not self._backend.exists(self.key):
            return ()
        raw = self._backend.get_json(self.key)
        return tuple(WikiPage.model_validate(item) for item in raw)

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

    def _write_markdown(self, pages: tuple[WikiPage, ...]) -> None:
        """Write the browsable tree: one .md per page + a table-of-contents index."""
        # Clear stale page files from a previous build (trailing slash keeps
        # the sibling pages.json out of the prefix match).
        self._backend.delete_prefix(f"{self._prefix}/pages/")
        for page in pages:
            self._backend.put_bytes(self.page_key(page.page_id), _page_markdown(page))
        self._backend.put_bytes(self.index_key, _index_markdown(pages))


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


def _index_markdown(pages: tuple[WikiPage, ...]) -> bytes:
    lines = ["# Wiki Index", ""]
    lines += [f"- [{page.title}](pages/{_slug(page.page_id)}.md)" for page in pages]
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
