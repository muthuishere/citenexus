"""S3-native wiki/navigation pages over Evidence Units.

Wiki pages are navigation aids, never citation targets. Each hit resolves to the
page's underlying EU refs before the answer path sees it.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from trustrag.answer.verify import content_tokens
from trustrag.domain.partition import PartitionPath
from trustrag.storage.backend import StorageBackend
from trustrag.storage.lance_store import LeafVectorStore
from trustrag.storage.paths import Layer, layer_prefix

_WIKI_FILE = "pages.json"


class WikiPage(BaseModel):
    """One generated navigation page for a document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_id: str
    title: str
    summary: str
    keywords: tuple[str, ...]
    eu_refs: tuple[str, ...]


class WikiStore:
    """Persist and load wiki pages for one partition."""

    def __init__(self, backend: StorageBackend, partition: PartitionPath) -> None:
        self._backend = backend
        self._partition = partition

    @property
    def key(self) -> str:
        return f"{layer_prefix(Layer.knowledge, self._partition)}/wiki/{_WIKI_FILE}"

    def build_from_store(self, store: LeafVectorStore) -> tuple[WikiPage, ...]:
        rows_by_doc: dict[str, list[dict[str, object]]] = {}
        for row in store.scan():
            rows_by_doc.setdefault(str(row.get("document_id", row["eu_id"])), []).append(row)

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

    def load(self) -> tuple[WikiPage, ...]:
        if not self._backend.exists(self.key):
            return ()
        raw = self._backend.get_json(self.key)
        return tuple(WikiPage.model_validate(item) for item in raw)


def _top_keywords(text: str, limit: int = 12) -> tuple[str, ...]:
    counts = Counter(content_tokens(text))
    return tuple(token for token, _count in counts.most_common(limit))


def _summary(texts: list[str], max_chars: int = 240) -> str:
    joined = " ".join(texts).strip()
    if len(joined) <= max_chars:
        return joined
    return joined[: max_chars - 1].rstrip() + "."
